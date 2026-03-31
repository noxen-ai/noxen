/**
 * Noxen — Chat Tab Component
 * SSE streaming chat with ReadableStream.
 */
function chatComponent() {
  return {
    messages: [],
    input: '',
    streaming: false,
    statusText: '',
    kbInfo: '',
    llmInfo: '',

    async init() {
      try {
        const status = await NoxenAPI.status();
        this.statusText = status.initialized ? 'Ready' : 'Not initialized';
        this.kbInfo = status.project_name ? `Project: ${status.project_name}` : '';
        this.llmInfo = status.active_provider ? `LLM: ${status.active_provider}` : '';
      } catch {}
    },

    async sendMessage() {
      const text = this.input.trim();
      if (!text || this.streaming) return;

      this.messages.push({ role: 'user', content: text, streaming: false });
      this.input = '';
      this.streaming = true;

      // Add AI placeholder
      const aiMsg = { role: 'assistant', content: '', streaming: true };
      this.messages.push(aiMsg);
      this.scrollToBottom();

      try {
        const res = await NoxenAPI.chatStream(text);
        const reader = res.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';

        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });

          // Parse SSE lines
          const lines = buffer.split('\n');
          buffer = lines.pop() || '';

          for (const line of lines) {
            if (line.startsWith('data: ')) {
              const data = line.slice(6);
              if (data === '[DONE]') continue;
              try {
                const parsed = JSON.parse(data);
                if (parsed.token) aiMsg.content += parsed.token;
                else if (parsed.content) aiMsg.content += parsed.content;
                else if (parsed.response) aiMsg.content = parsed.response;
              } catch {
                // Plain text token
                aiMsg.content += data;
              }
              this.scrollToBottom();
            }
          }
        }
      } catch (e) {
        aiMsg.content = aiMsg.content || `Error: ${e.message}`;
      }

      aiMsg.streaming = false;
      this.streaming = false;
    },

    clearChat() {
      this.messages = [];
    },

    scrollToBottom() {
      this.$nextTick(() => {
        const el = document.getElementById('chat-messages-container');
        if (el) el.scrollTop = el.scrollHeight;
      });
    },
  };
}
