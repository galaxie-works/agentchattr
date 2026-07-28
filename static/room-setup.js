/* First-run room creation. Kept separate from chat.js so the chat runtime
 * remains available after the onboarding overlay closes. */
const RoomSetup = (() => {
    const root = document.getElementById('room-onboarding');
    const landing = root.querySelector('.room-landing');
    const wizard = root.querySelector('.room-wizard');
    const board = root.querySelector('.room-board');
    const createButton = document.getElementById('create-room-button');
    const boardButton = document.getElementById('go-to-board-button');
    const state = { data: null, selected: [], step: 0, active: true, threads: {}, terminateActiveClaudeSessions: false, createdThisVisit: false, rooms: [], selectedRoom: null, terminateBoardClaude: false, setupPreflight: null, boardPreflight: null };

    const escape = (value) => String(value ?? '').replace(/[&<>'"]/g, c => ({
        '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;',
    })[c]);

    function preflightWarning(items) {
        const rows = (items || []).map(item => {
            const command = [item.command, ...(item.full_control_args || [])].join(' ');
            return `<li><strong>${escape(item.label)}</strong><small>${escape(item.cwd)}</small><code>${escape(command)}</code></li>`;
        }).join('');
        return `<div class="room-preflight-warning"><strong>Workspace trust and full control required</strong><p>Continue to open a visible CLI for each provider. Confirm that you trust the directory. The command shown below disables that provider’s approval/sandbox prompts; AgentChattr will close the bootstrap window and resume automatically.</p><ul>${rows}</ul></div>`;
    }

    async function runProviderPreflight(startUrl, body, error, onReady) {
        error.innerHTML = '<span>Opening visible provider trust windows…</span>';
        const response = await fetch(startUrl, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-Session-Token': SESSION_TOKEN },
            body: body ? JSON.stringify(body) : '{}',
        });
        let payload = await response.json();
        if (!response.ok) throw new Error(payload.error || 'Could not start provider preflight.');
        if (payload.status === 'ready' && !payload.id) { await onReady(); return; }
        error.innerHTML = '<span>Confirm workspace trust in the visible CLI window. Waiting…</span>';
        while (payload.status === 'starting' || payload.status === 'waiting') {
            await new Promise(resolve => setTimeout(resolve, 500));
            const statusResponse = await fetch(`/api/provider-preflight/${encodeURIComponent(payload.id)}`, {
                headers: { 'X-Session-Token': SESSION_TOKEN },
            });
            payload = await statusResponse.json();
            if (!statusResponse.ok) throw new Error(payload.error || 'Provider preflight could not be read.');
        }
        if (payload.status !== 'ready') throw new Error(payload.error || 'Provider preflight failed.');
        error.innerHTML = '<span>Workspace trust confirmed. Resuming…</span>';
        await onReady();
    }

    async function load() {
        const response = await fetch('/api/room-setup', { headers: { 'X-Session-Token': SESSION_TOKEN } });
        if (!response.ok) throw new Error('Could not load available colleagues.');
        state.data = await response.json();
    }

    function applySettings(settings) {
        const created = Boolean(settings && settings.setup_complete);
        state.active = !state.createdThisVisit;
        root.classList.toggle('active', !state.createdThisVisit);
        root.classList.toggle('hidden', state.createdThisVisit);
        if (created) boardButton.classList.remove('hidden');
    }

    function openWizard() {
        landing.classList.add('hidden');
        board.classList.add('hidden');
        wizard.classList.remove('hidden');
        if (!state.data) {
            wizard.innerHTML = '<p class="room-loading">Loading colleagues…</p>';
            load().then(render).catch(error => { wizard.innerHTML = `<p class="room-error">${escape(error.message)}</p>`; });
        } else {
            render();
        }
    }

    async function openBoard() {
        landing.classList.add('hidden');
        wizard.classList.add('hidden');
        board.classList.remove('hidden');
        board.innerHTML = '<p class="room-loading">Loading chat rooms…</p>';
        try {
            const response = await fetch('/api/rooms', { headers: { 'X-Session-Token': SESSION_TOKEN } });
            if (!response.ok) throw new Error('Could not load chat rooms.');
            state.rooms = await response.json();
            state.selectedRoom = state.rooms[0] || null;
            renderBoard();
        } catch (error) { board.innerHTML = `<p class="room-error">${escape(error.message)}</p>`; }
    }

    function renderBoard() {
        const selected = state.selectedRoom;
        const rooms = state.rooms.map(room => `<button type="button" class="room-history-item ${selected?.id === room.id ? 'selected' : ''}" data-room-id="${escape(room.id)}"><strong>${escape(room.title)}</strong><small>${escape(room.member_count)} colleagues · ${escape(room.last_activity || 'saved room')}</small></button>`).join('') || '<small>No saved rooms yet.</small>';
        const members = selected?.members?.length ? selected.members.map(escape).join(', ') : 'No configured colleagues';
        const continueLabel = state.boardPreflight ? 'Open trust windows and continue' : (state.terminateBoardClaude ? 'Close session and continue' : 'Continue room');
        board.innerHTML = `<div class="room-board-layout"><aside class="room-board-sidebar"><h3>Chat history</h3>${rooms}<button class="room-secondary-button" id="board-back">Back</button></aside><div class="room-board-detail">${selected ? `<h2>${escape(selected.title)}</h2><p>${escape(selected.description || 'No description')}</p><div class="room-board-members">${members}</div><div class="room-board-actions"><button class="room-primary-button" id="continue-room">${continueLabel}</button><span class="room-board-error" id="board-error">${state.boardPreflight ? preflightWarning(state.boardPreflight) : ''}</span></div>` : '<h2>Select a room</h2>'}</div></div>`;
        board.querySelectorAll('[data-room-id]').forEach(button => button.addEventListener('click', () => { state.selectedRoom = state.rooms.find(room => room.id === button.dataset.roomId); state.terminateBoardClaude = false; state.boardPreflight = null; renderBoard(); }));
        board.querySelector('#board-back')?.addEventListener('click', () => { board.classList.add('hidden'); landing.classList.remove('hidden'); });
        board.querySelector('#continue-room')?.addEventListener('click', continueRoom);
    }

    async function continueRoom() {
        const button = board.querySelector('#continue-room'); const error = board.querySelector('#board-error');
        button.disabled = true; error.textContent = 'Waking up colleagues…';
        try {
            if (state.boardPreflight) {
                await runProviderPreflight('/api/provider-preflight/room', null, error, async () => {
                    state.boardPreflight = null;
                    button.disabled = false;
                    await continueRoom();
                });
                return;
            }
            const response = await fetch(`/api/rooms/${encodeURIComponent(state.selectedRoom.id)}/continue`, { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Session-Token': SESSION_TOKEN }, body: JSON.stringify({ terminate_active_claude_sessions: state.terminateBoardClaude }) });
            const payload = await response.json();
            if (payload.requires_provider_preflight) {
                state.boardPreflight = payload.provider_preflight || [];
                error.innerHTML = preflightWarning(state.boardPreflight);
                button.textContent = 'Open trust windows and continue';
                button.disabled = false;
                return;
            }
            if (payload.requires_session_termination) { state.terminateBoardClaude = true; error.textContent = 'A Claude session is open. Continue again to close it and wake the room.'; button.textContent = 'Close session and continue'; button.disabled = false; return; }
            if (!response.ok) throw new Error(payload.error || 'Could not continue room.');
            state.createdThisVisit = true; root.classList.remove('active'); root.classList.add('hidden');
        } catch (err) { error.textContent = err.message || 'Could not continue room.'; button.disabled = false; }
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
            return previous || { name, label: agent.label, provider: agent.provider, resumable: agent.resumable, cwd: agent.cwd || '', mode: 'standard' };
        });
    }

    function saveCurrentStep() {
        const stage = currentStage();
        if (stage.kind === 'invite') { updateInvite(); return; }
        if (stage.kind === 'link') {
            const member = stage.member;
            member.cwd = wizard.querySelector('.room-cwd')?.value.trim() || '';
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
        }
        return '';
    }

    async function submit() {
        const button = wizard.querySelector('#room-next');
        const error = wizard.querySelector('#room-wizard-error');
        button.disabled = true;
        error.textContent = 'Creating room…';
        try {
            if (state.setupPreflight) {
                const setupBody = { title: state.title, description: state.description, agents: state.selected, terminate_active_claude_sessions: state.terminateActiveClaudeSessions };
                await runProviderPreflight('/api/provider-preflight/setup', setupBody, error, async () => {
                    state.setupPreflight = null;
                    button.disabled = false;
                    await submit();
                });
                return;
            }
            const response = await fetch('/api/room-setup', {
                method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Session-Token': SESSION_TOKEN },
                body: JSON.stringify({ title: state.title, description: state.description, agents: state.selected, terminate_active_claude_sessions: state.terminateActiveClaudeSessions }),
            });
            const payload = await response.json();
            if (payload.requires_provider_preflight) {
                state.setupPreflight = payload.provider_preflight || [];
                error.innerHTML = preflightWarning(state.setupPreflight);
                button.textContent = 'Open trust windows and create room';
                button.disabled = false;
                return;
            }
            if (payload.requires_session_termination) {
                state.terminateActiveClaudeSessions = true;
                const count = Array.isArray(payload.sessions) ? payload.sessions.length : 1;
                error.textContent = `${count} selected Claude session${count === 1 ? ' is' : 's are'} still open. Click “Close session and create room” to end ${count === 1 ? 'it' : 'them'} and continue.`;
                button.textContent = 'Close session and create room';
                button.disabled = false;
                return;
            }
            if (!response.ok) throw new Error(payload.error || 'Could not create room.');
            state.createdThisVisit = true; applySettings({ setup_complete: true });
        } catch (err) {
            error.textContent = err.message || 'Could not create room.';
            button.disabled = false;
        }
    }

    function bind() {
        wizard.querySelectorAll('[data-agent-name]').forEach(input => input.addEventListener('change', () => { state.terminateActiveClaudeSessions = false; state.setupPreflight = null; updateInvite(); render(); }));
        wizard.querySelectorAll('[data-mode]').forEach(button => button.addEventListener('click', () => {
            const stage = currentStage();
            state.terminateActiveClaudeSessions = false;
            state.setupPreflight = null;
            stage.member.mode = button.dataset.mode;
            state.step += 1;
            render();
        }));
        wizard.querySelectorAll('[data-thread-index]').forEach(button => button.addEventListener('click', () => {
            const stage = currentStage();
            state.terminateActiveClaudeSessions = false;
            state.setupPreflight = null;
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
    boardButton.addEventListener('click', openBoard);
    return { applySettings, load };
})();
