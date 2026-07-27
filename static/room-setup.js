/* First-run room creation. Kept separate from chat.js so the chat runtime
 * remains available after the onboarding overlay closes. */
const RoomSetup = (() => {
    const root = document.getElementById('room-onboarding');
    const landing = root.querySelector('.room-landing');
    const wizard = root.querySelector('.room-wizard');
    const createButton = document.getElementById('create-room-button');
    const state = { data: null, selected: [], step: 0, active: true, threads: {} };

    const escape = (value) => String(value ?? '').replace(/[&<>'"]/g, c => ({
        '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;',
    })[c]);

    async function load() {
        const response = await fetch('/api/room-setup', { headers: { 'X-Session-Token': SESSION_TOKEN } });
        if (!response.ok) throw new Error('Could not load available colleagues.');
        state.data = await response.json();
    }

    function applySettings(settings) {
        const created = Boolean(settings && settings.setup_complete);
        state.active = !created;
        root.classList.toggle('active', !created);
        if (created) root.classList.add('hidden');
    }

    function openWizard() {
        landing.classList.add('hidden');
        wizard.classList.remove('hidden');
        if (!state.data) {
            wizard.innerHTML = '<p class="room-loading">Loading colleagues…</p>';
            load().then(render).catch(error => { wizard.innerHTML = `<p class="room-error">${escape(error.message)}</p>`; });
        } else {
            render();
        }
    }

    function inviteStep() {
        const cards = state.data.available_agents.map(agent => {
            const selected = state.selected.some(item => item.name === agent.name);
            const icon = window.PROVIDER_ICONS?.paths?.[agent.provider];
            const initial = escape((agent.label || agent.provider || '?').slice(0, 1).toUpperCase());
            return `<label class="room-agent-option ${selected ? 'selected' : ''}">
                <input class="room-agent-native-check" type="checkbox" data-agent-name="${escape(agent.name)}" ${selected ? 'checked' : ''}>
                <span class="room-agent-check" aria-hidden="true"><svg viewBox="0 0 16 16" focusable="false"><path d="m3.25 8.25 3 3 6.5-6.5"/></svg></span>
                <span class="room-agent-logo" style="--agent-color:${escape(agent.color)}">
                    ${icon ? `<img src="${escape(icon)}" alt="" aria-hidden="true">` : `<b>${initial}</b>`}
                </span>
                <span class="room-agent-copy"><strong>${escape(agent.label)}</strong><small>${escape(agent.provider)}</small></span>
            </label>`;
        }).join('');
        return `<h2>Invite your colleagues</h2><p>Choose the AI colleagues that should join this room.</p>
            <div class="room-agent-grid">${cards}</div>`;
    }

    function formatActivity(value) {
        const date = new Date(value);
        return Number.isNaN(date.getTime()) ? 'Unknown activity' : date.toLocaleString();
    }

    function customFields(member) {
        const provider = member.provider;
        const threads = state.threads[provider];
        const claudeWarning = provider === 'claude' ? `<label class="room-confirm"><input type="checkbox" class="room-claude-confirm" ${member.confirm ? 'checked' : ''}> I will close the currently open Claude Code session before this room starts it.</label>` : '';
        if (!Array.isArray(threads)) {
            return `<div class="room-thread-loading">Discovering local ${escape(member.label)} conversations…</div>`;
        }
        if (threads.length === 0) {
            return `<div class="room-thread-empty">No resumable ${escape(member.label)} conversations were found. Go back and use the managed app session instead.</div>`;
        }
        const cards = threads.map((thread, index) => {
            const selected = member.target === thread.id;
            const context = [thread.cwd, thread.git_branch ? `branch ${thread.git_branch}` : ''].filter(Boolean).join(' · ');
            return `<button type="button" class="room-thread-option ${selected ? 'selected' : ''}" data-thread-index="${index}">
                <span><strong>${escape(thread.name || thread.id)}</strong><small>${escape(formatActivity(thread.last_activity))}${context ? ` · ${escape(context)}` : ''}</small></span>
                <b aria-hidden="true">›</b>
            </button>`;
        }).join('');
        return `<div class="room-custom-fields">
            <div class="room-thread-list">${cards}</div>
            ${member.target ? `<label>Working directory<input class="room-cwd" value="${escape(member.cwd || '')}" placeholder="C:\\project"></label>` : ''}
            ${claudeWarning}
        </div>`;
    }

    function architectureStep(member) {
        const customAllowed = member.resumable;
        return `<h2>Configure ${escape(member.label)}</h2>
            <p>Choose the architecture for ${escape(member.label)} in this room.</p>
            <div class="room-mode-options">
                <button class="room-mode-card" data-mode="standard">
                    <span><strong>Managed by AgentChattr</strong><small>Starts a new provider session through the app wrapper, with MCP injection and its project tools.</small></span>
                    <b aria-hidden="true">›</b>
                </button>
                ${customAllowed ? `<button class="room-mode-card" data-mode="custom">
                    <span><strong>Use custom architecture</strong><small>${customAllowed ? 'Link one explicit existing thread or session in the next step.' : 'Thread/session linking is currently available for Codex and Claude.'}</small></span>
                    <b aria-hidden="true">›</b>
                </button>` : ''}
            </div>`;
    }

    function linkStep(member) {
        return `<h2>Link ${escape(member.label)}</h2>
            <p>Connect the conversation that should receive room messages.</p>
            ${customFields(member)}`;
    }

    async function loadThreads(provider) {
        if (state.threads[provider] !== undefined) return;
        state.threads[provider] = null;
        try {
            const response = await fetch(`/api/threads?provider=${encodeURIComponent(provider)}`, { headers: { 'X-Session-Token': SESSION_TOKEN } });
            if (!response.ok) throw new Error('Thread discovery failed.');
            const threads = await response.json();
            state.threads[provider] = Array.isArray(threads) ? threads.filter(thread => !thread.relay_bot) : [];
        } catch {
            state.threads[provider] = [];
        }
        render();
    }

    function reviewStep() {
        const members = state.selected.map(member => `<li><strong>${escape(member.label)}</strong> · ${member.mode === 'custom' ? `custom ${escape(member.target || '(target missing)')}` : 'managed session'}</li>`).join('');
        return `<h2>Review your room</h2><p>The room opens as soon as the selected local workers are started.</p>
            <label>Room name<input id="room-name" value="${escape(state.title || 'New room')}" maxlength="80"></label>
            <label>Short description<textarea id="room-description" maxlength="240" placeholder="What is this room for?">${escape(state.description || '')}</textarea></label>
            <ul class="room-review-list">${members}</ul>`;
    }

    function stages() {
        const result = [{ kind: 'invite' }];
        state.selected.forEach(member => {
            result.push({ kind: 'architecture', member });
            if (member.mode === 'custom') result.push({ kind: 'link', member });
        });
        result.push({ kind: 'review' });
        return result;
    }

    function currentStage() {
        return stages()[state.step] || { kind: 'review' };
    }

    function currentContent() {
        const stage = currentStage();
        if (stage.kind === 'invite') return inviteStep();
        if (stage.kind === 'architecture') return architectureStep(stage.member);
        if (stage.kind === 'link') return linkStep(stage.member);
        return reviewStep();
    }

    function render() {
        const flow = stages();
        const stage = currentStage();
        const total = flow.length;
        const isInvite = stage.kind === 'invite';
        const isReview = stage.kind === 'review';
        const isArchitecture = stage.kind === 'architecture';
        wizard.innerHTML = `<div class="room-stepper"><span>Step ${state.step + 1} of ${total}</span><div>${Array.from({ length: total }, (_, i) => `<i class="${i <= state.step ? 'active' : ''}"></i>`).join('')}</div></div>
            <div class="room-step-content">${currentContent()}</div>
            <div class="room-wizard-actions">
                <button class="room-secondary-button" id="room-back" ${isInvite ? 'disabled' : ''}>Back</button>
                <span class="room-error" id="room-wizard-error"></span>
                ${isArchitecture ? '' : `<button class="room-primary-button" id="room-next">${isReview ? 'Create room' : 'Continue'}</button>`}
            </div>`;
        bind();
        if (stage.kind === 'link') loadThreads(stage.member.provider);
    }

    function updateInvite() {
        const checked = [...wizard.querySelectorAll('[data-agent-name]:checked')].map(input => input.dataset.agentName);
        state.selected = checked.map(name => {
            const previous = state.selected.find(member => member.name === name);
            const agent = state.data.available_agents.find(item => item.name === name);
            return previous || { name, label: agent.label, provider: agent.provider, resumable: agent.resumable, defaultCwd: agent.cwd, mode: 'standard' };
        });
    }

    function saveCurrentStep() {
        const stage = currentStage();
        if (stage.kind === 'invite') { updateInvite(); return; }
        if (stage.kind === 'link') {
            const member = stage.member;
            member.cwd = wizard.querySelector('.room-cwd')?.value.trim() || '';
            member.confirm = Boolean(wizard.querySelector('.room-claude-confirm')?.checked);
            return;
        }
        if (stage.kind === 'review') {
            state.title = wizard.querySelector('#room-name').value.trim();
            state.description = wizard.querySelector('#room-description').value.trim();
        }
    }

    function validateCurrentStep() {
        const stage = currentStage();
        if (stage.kind === 'invite' && state.selected.length === 0) return 'Choose at least one colleague.';
        if (stage.kind === 'link') {
            const member = stage.member;
            if (!member.target || !member.cwd) return 'A target and working directory are required.';
            if (member.provider === 'claude' && !member.confirm) return 'Confirm that the current Claude session will be closed first.';
        }
        return '';
    }

    async function submit() {
        const button = wizard.querySelector('#room-next');
        const error = wizard.querySelector('#room-wizard-error');
        button.disabled = true;
        error.textContent = 'Creating room…';
        try {
            const response = await fetch('/api/room-setup', {
                method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Session-Token': SESSION_TOKEN },
                body: JSON.stringify({ title: state.title, description: state.description, agents: state.selected, confirm_claude_resume: state.selected.some(member => member.provider === 'claude' && member.mode === 'custom' && member.confirm) }),
            });
            const payload = await response.json();
            if (!response.ok) throw new Error(payload.error || 'Could not create room.');
            applySettings({ setup_complete: true });
        } catch (err) {
            error.textContent = err.message || 'Could not create room.';
            button.disabled = false;
        }
    }

    function bind() {
        wizard.querySelectorAll('[data-agent-name]').forEach(input => input.addEventListener('change', () => { updateInvite(); render(); }));
        wizard.querySelectorAll('[data-mode]').forEach(button => button.addEventListener('click', () => {
            const stage = currentStage();
            stage.member.mode = button.dataset.mode;
            state.step += 1;
            render();
        }));
        wizard.querySelectorAll('[data-thread-index]').forEach(button => button.addEventListener('click', () => {
            const stage = currentStage();
            const thread = state.threads[stage.member.provider][Number(button.dataset.threadIndex)];
            stage.member.target = thread.id;
            stage.member.cwd = thread.cwd || stage.member.cwd || '';
            render();
        }));
        wizard.querySelector('#room-back').addEventListener('click', () => { saveCurrentStep(); state.step = Math.max(0, state.step - 1); render(); });
        wizard.querySelector('#room-next')?.addEventListener('click', async () => {
            saveCurrentStep();
            const error = validateCurrentStep();
            if (error) { wizard.querySelector('#room-wizard-error').textContent = error; return; }
            if (currentStage().kind === 'review') { await submit(); return; }
            state.step += 1; render();
        });
    }

    createButton.addEventListener('click', openWizard);
    return { applySettings, load };
})();
