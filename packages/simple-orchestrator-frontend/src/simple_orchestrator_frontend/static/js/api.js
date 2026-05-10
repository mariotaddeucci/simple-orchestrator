class OrchestratorApi {
    constructor(apiUrl, apiKey) {
        this.apiUrl = apiUrl.replace(/\/$/, '');
        this.apiKey = apiKey;
    }

    async request(path, options = {}) {
        const url = `${this.apiUrl}${path}`;
        const headers = {
            'Content-Type': 'application/json',
            'X-API-Key': this.apiKey,
            ...options.headers,
        };

        const response = await fetch(url, { ...options, headers });
        if (response.status === 204) return null;
        if (!response.ok) {
            const error = await response.json().catch(() => ({ detail: response.statusText }));
            throw new Error(error.detail || response.statusText);
        }
        return response.json();
    }

    // Agents
    listAgents() { return this.request('/agents'); }
    getAgent(id) { return this.request(`/agents/${id}`); }
    upsertAgent(agent) { return this.request('/agents', { method: 'POST', body: JSON.stringify(agent) }); }
    deleteAgent(id) { return this.request(`/agents/${id}`, { method: 'DELETE' }); }

    // Queue
    listQueue(params = {}) {
        const query = new URLSearchParams(params).toString();
        return this.request(`/queue${query ? '?' + query : ''}`);
    }
    enqueue(data) { return this.request('/queue', { method: 'POST', body: JSON.stringify(data) }); }
    cancelQueueItem(id) { return this.request(`/queue/${id}/cancel`, { method: 'POST' }); }

    // MCPs
    listMcps() { return this.request('/mcps'); }
    getMcp(id) { return this.request(`/mcps/${id}`); }
    upsertMcp(mcp) { return this.request('/mcps', { method: 'POST', body: JSON.stringify(mcp) }); }
    deleteMcp(id) { return this.request(`/mcps/${id}`, { method: 'DELETE' }); }

    // Events
    listEvents() { return this.request('/events'); }
    getEvent(id) { return this.request(`/events/${id}`); }
    createEvent(event) { return this.request('/events', { method: 'POST', body: JSON.stringify(event) }); }
    updateEvent(id, event) { return this.request(`/events/${id}`, { method: 'PATCH', body: JSON.stringify(event) }); }
    deleteEvent(id) { return this.request(`/events/${id}`, { method: 'DELETE' }); }
    triggerEvent(id) { return this.request(`/events/${id}/trigger`, { method: 'POST' }); }

    // Sessions
    listSessions(params = {}) {
        const query = new URLSearchParams(params).toString();
        return this.request(`/sessions${query ? '?' + query : ''}`);
    }
    getSession(id) { return this.request(`/sessions/${id}`); }
}
