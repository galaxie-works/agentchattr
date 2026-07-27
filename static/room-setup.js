/* First-run room creation. Kept separate from chat.js so the chat runtime
 * remains available after the onboarding overlay closes. */
const RoomSetup = (() => {
    const root = document.getElementById('room-onboarding');
    const landing = root.querySelector('.room-landing');
    const wizard = root.querySelector('.room-wizard');
    const createButton = document.getElementById('create-room-button');
    const state = { data: null, selected: [], step: 0, active: true };

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
            return `<label class="room-agent-option ${selected ? 'selected' : ''}">
                <input type="checkbox" data-agent-name="${escape(agent.name)}" ${selected ? 'checked' : ''}>
                <span class="room-agent-dot" style="--agent-color:${escape(agent.color)}"></span>
                <span><strong>${escape(agent.label)}</strong><small>${escape(agent.provider)}</small></span>
            </label>`;
        }).join('');
        return `<h2>Invite your colleagues</h2><p>Choose the AI colleagues that should join this room.</p>
            <div class="room-agent-grid">${cards}</div>`;
    }

    function customFields(member) {
        const provider = member.provider;
        const known = (state.data.known_targets[provider] || []).map(item =>
            `<option value="${escape(item.value)}">${escape(item.label)}</option>`
        ).join('');
        const listId = `known-${provider}-targets`;
        const targetHint = provider === 'codex'
            ? 'A Codex thread ID or saved thread name.'
            : 'A Claude Code session UUID. The wrapper will resume it with MCP injection.';
        const claudeWarning = provider === 'claude' ? `<label class="room-confirm"><input type="checkbox" class="room-claude-confirm" ${member.confirm ? 'checked' : ''}> I will close the currently open Claude Code session before this room starts it.</label>` : '';
        return `<div class="room-custom-fields">
            <label>Thread or session target<input class="room-target" list="${listId}" value="${escape(member.target || '')}" placeholder="${provider === 'codex' ? 'Thread ID or name' : 'Session UUID'}"></label>
            <datalist id="${listId}">${known}</datalist>
            <small>${targetHint}</small>
            <label>Working directory<input class="room-cwd" value="${escape(member.cwd || member.defaultCwd || '')}" placeholder="C:\\project"></label>
            ${claudeWarning}
        </div>`;
    }

    function agentStep(member) {
        const customAllowed = member.custom_supported;
        return `<h2>Configure ${escape(member.label)}</h2>
            <p>Choose how ${escape(member.label)} should participate in this room.</p>
            <div class="room-mode-options">
                <label class="room-mode ${member.mode === 'standard' ? 'selected' : ''}">
                    <input type="radio" name="mode" value="standard" ${member.mode === 'standard' ? 'checked' : ''}>
                    <strong>Managed by AgentChattr</strong>
                    <span>Starts a new provider session through the app wrapper, with MCP injection and its project tools.</span>
                </label>
                <label class="room-mode ${member.mode === 'custom' ? 'selected' : ''} ${customAllowed ? '' : 'disabled'}">
                    <input type="radio" name="mode" value="custom" ${member.mode === 'custom' ? 'checked' : ''} ${customAllowed ? '' : 'disabled'}>
                    <strong>Use custom architecture</strong>
                    <span>${customAllowed ? 'Link one explicit existing thread or session.' : 'Thread/session linking is currently available for Codex and Claude.'}</span>
                </label>
            </div>
            ${member.mode === 'custom' && customAllowed ? customFields(member) : ''}`;
    }

    function reviewStep() {
        const members = state.selected.map(member => `<li><strong>${escape(member.label)}</strong> · ${member.mode === 'custom' ? `custom ${escape(member.target || '(target missing)')}` : 'managed session'}</li>`).join('');
        return `<h2>Review your room</h2><p>The room opens as soon as the selected local workers are started.</p>
            <label>Room name<input id="room-name" value="${escape(state.title || 'New room')}" maxlength="80"></label>
            <label>Short description<textarea id="room-description" maxlength="240" placeholder="What is this room for?">${escape(state.description || '')}</textarea></label>
            <ul class="room-review-list">${members}</ul>`;
    }

    function currentContent() {
        if (state.step === 0) return inviteStep();
        const agentIndex = state.step - 1;
        if (agentIndex < state.selected.length) return agentStep(state.selected[agentIndex]);
        return reviewStep();
    }

    function render() {
        const total = state.selected.length + 2;
        const isInvite = state.step === 0;
        const isReview = state.step === total - 1;
        wizard.innerHTML = `<div class="room-stepper"><span>Step ${state.step + 1} of ${total}</span><div>${Array.from({ length: total }, (_, i) => `<i class="${i <= state.step ? 'active' : ''}"></i>`).join('')}</div></div>
            <div class="room-step-content">${currentContent()}</div>
            <div class="room-wizard-actions">
                <button class="room-secondary-button" id="room-back" ${isInvite ? 'disabled' : ''}>Back</button>
                <span class="room-error" id="room-wizard-error"></span>
                <button class="room-primary-button" id="room-next">${isReview ? 'Create room' : 'Continue'}</button>
            </div>`;
        bind();
    }

    function updateInvite() {
        const checked = [...wizard.querySelectorAll('[data-agent-name]:checked')].map(input => input.dataset.agentName);
        state.selected = checked.map(name => {
            const previous = state.selected.find(member => member.name === name);
            const agent = state.data.available_agents.find(item => item.name === name);
            return previous || { name, label: agent.label, provider: agent.provider, custom_supported: agent.custom_supported, defaultCwd: agent.cwd, mode: 'standard' };
        });
    }

    function saveCurrentStep() {
        if (state.step === 0) { updateInvite(); return; }
        const index = state.step - 1;
        if (index < state.selected.length) {
            const member = state.selected[index];
            const selectedMode = wizard.querySelector('input[name="mode"]:checked');
            member.mode = selectedMode ? selectedMode.value : 'standard';
            if (member.mode === 'custom') {
                member.target = wizard.querySelector('.room-target')?.value.trim() || '';
                member.cwd = wizard.querySelector('.room-cwd')?.value.trim() || '';
                member.confirm = Boolean(wizard.querySelector('.room-claude-confirm')?.checked);
            }
            return;
        }
        state.title = wizard.querySelector('#room-name').value.trim();
        state.description = wizard.querySelector('#room-description').value.trim();
    }

    function validateCurrentStep() {
        if (state.step === 0 && state.selected.length === 0) return 'Choose at least one colleague.';
        const index = state.step - 1;
        if (index >= 0 && index < state.selected.length) {
            const member = state.selected[index];
            if (member.mode === 'custom' && (!member.target || !member.cwd)) return 'A target and working directory are required.';
            if (member.provider === 'claude' && member.mode === 'custom' && !member.confirm) return 'Confirm that the current Claude session will be closed first.';
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
        wizard.querySelectorAll('input[name="mode"]').forEach(input => input.addEventListener('change', () => { saveCurrentStep(); render(); }));
        wizard.querySelector('#room-back').addEventListener('click', () => { saveCurrentStep(); state.step = Math.max(0, state.step - 1); render(); });
        wizard.querySelector('#room-next').addEventListener('click', async () => {
            saveCurrentStep();
            const error = validateCurrentStep();
            if (error) { wizard.querySelector('#room-wizard-error').textContent = error; return; }
            if (state.step === state.selected.length + 1) { await submit(); return; }
            state.step += 1; render();
        });
    }

    createButton.addEventListener('click', openWizard);
    return { applySettings, load };
})();
