const endpoint = process.env.PLAYWRIGHT_MCP_URL || 'http://127.0.0.1:8931/mcp';

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

function decodeResponse(text, contentType) {
  if (!text.trim()) return undefined;
  if (contentType.includes('text/event-stream')) {
    const payloads = text
      .split(/\r?\n/)
      .filter(line => line.startsWith('data:'))
      .map(line => line.slice(5).trim())
      .filter(value => value && value !== '[DONE]');
    if (!payloads.length) return undefined;
    return JSON.parse(payloads.at(-1));
  }
  return JSON.parse(text);
}

class McpClient {
  constructor(name) {
    this.name = name;
    this.nextId = 1;
    this.sessionId = undefined;
  }

  async send(method, params, notification = false) {
    const body = { jsonrpc: '2.0', method };
    if (!notification) body.id = this.nextId++;
    if (params !== undefined) body.params = params;

    const headers = {
      accept: 'application/json, text/event-stream',
      'content-type': 'application/json',
    };
    if (this.sessionId) headers['mcp-session-id'] = this.sessionId;

    const response = await fetch(endpoint, {
      method: 'POST',
      headers,
      body: JSON.stringify(body),
    });
    const newSessionId = response.headers.get('mcp-session-id');
    if (newSessionId) this.sessionId = newSessionId;
    const text = await response.text();
    if (!response.ok) {
      throw new Error(`${this.name}: ${method} returned HTTP ${response.status}: ${text}`);
    }

    const message = decodeResponse(text, response.headers.get('content-type') || '');
    if (message?.error) {
      throw new Error(`${this.name}: ${method} failed: ${JSON.stringify(message.error)}`);
    }
    return message?.result;
  }

  async initialize() {
    const result = await this.send('initialize', {
      protocolVersion: '2025-06-18',
      capabilities: {},
      clientInfo: { name: `docker-local-${this.name}`, version: '1.0.0' },
    });
    assert(this.sessionId, `${this.name}: server did not issue an MCP session ID`);
    assert(result?.serverInfo?.name, `${this.name}: initialize returned no server info`);
    await this.send('notifications/initialized', undefined, true);
    return result;
  }

  async callTool(name, args = {}) {
    const result = await this.send('tools/call', { name, arguments: args });
    if (result?.isError) throw new Error(`${this.name}: ${name} returned an MCP tool error: ${JSON.stringify(result)}`);
    return result;
  }

  async close() {
    if (!this.sessionId) return;
    try {
      await this.callTool('browser_close');
    } finally {
      await fetch(endpoint, {
        method: 'DELETE',
        headers: { 'mcp-session-id': this.sessionId },
      }).catch(() => undefined);
    }
  }
}

const first = new McpClient('session-a');
const second = new McpClient('session-b');

try {
  const server = await first.initialize();
  const toolsResult = await first.send('tools/list', {});
  const tools = toolsResult?.tools || [];
  const toolNames = new Set(tools.map(tool => tool.name));
  for (const required of ['browser_navigate', 'browser_evaluate', 'browser_close']) {
    assert(toolNames.has(required), `required MCP tool is missing: ${required}`);
  }

  const navigation = await first.callTool('browser_navigate', { url: 'https://example.com' });
  assert(JSON.stringify(navigation).includes('Example Domain'), 'navigation did not reach Example Domain');
  const firstEvaluation = await first.callTool('browser_evaluate', {
    function: "() => { localStorage.setItem('dockerLocalProbe', 'session-a'); return document.title; }",
  });
  assert(JSON.stringify(firstEvaluation).includes('Example Domain'), 'browser evaluation did not return the page title');

  await second.initialize();
  await second.callTool('browser_navigate', { url: 'https://example.com' });
  const isolatedEvaluation = await second.callTool('browser_evaluate', {
    function: "() => localStorage.getItem('dockerLocalProbe')",
  });
  const isolatedText = JSON.stringify(isolatedEvaluation);
  assert(!isolatedText.includes('session-a'), 'separate MCP clients unexpectedly shared browser storage');

  console.log(`Endpoint: ${endpoint}`);
  console.log(`Server: ${server.serverInfo.name} ${server.serverInfo.version || ''}`.trim());
  console.log(`Tools: ${tools.length}`);
  console.log('Browser navigation/evaluation: PASS');
  console.log('Cross-client storage isolation: PASS');
} finally {
  await Promise.allSettled([first.close(), second.close()]);
}
