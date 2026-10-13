(() => {
  const user = window.CHAT_USER;
  const config = window.CHAT_CONFIG;
  const el = (id) => document.getElementById(id);
  const messagesEl = el('messages');
  const pane = el('messagePane');
  const input = el('messageInput');
  const sendButton = el('sendButton');
  const imageInput = el('imageInput');
  const emojiButton = el('emojiButton');
  const emojiPanel = el('emojiPanel');
  const notificationButton = el('notificationButton');
  const loadMore = el('loadMore');
  const newMessages = el('newMessages');
  const typingEl = el('typing');
  const statusText = el('statusText');
  const statusDot = document.querySelector('.status-dot');
  let socket;
  let oldestId = null;
  let replyTo = null;
  let reconnectDelay = 1000;
  let pendingNewMessages = 0;
  let unreadTitleCount = 0;
  let typingTimer;
  const typers = new Map();
  const baseTitle = document.title;
  const emojis = [
    '😀','😄','😁','😂','🤣','😊','🥰','😍','😘','😋','😎','🤩','🥳','😏',
    '😅','🥹','😢','😭','😤','😡','🤔','🤭','🤫','😴','🙄','😮','😱','🤗',
    '👍','👎','👌','✌️','🤝','👏','🙏','💪','👀','🎉','✨','🔥','❤️','💔','💯',
    '🌹','🍉','☕','🎂','🎁','🐶','🐱','🌙','☀️','✅','❌'
  ];

  function escapeHtml(value) {
    const node = document.createElement('div');
    node.textContent = value ?? '';
    return node.innerHTML;
  }

  function formatTime(iso) {
    return new Intl.DateTimeFormat('zh-CN', {hour:'2-digit', minute:'2-digit'}).format(new Date(iso));
  }

  function messageText(message) {
    if (message.deleted) return '此消息已删除';
    if (message.kind === 'image') return message.content || '[图片]';
    return message.content;
  }

  function isNearBottom() {
    return pane.scrollHeight - pane.scrollTop - pane.clientHeight < 100;
  }

  function scrollToBottom() {
    pane.scrollTo({top: pane.scrollHeight, behavior: 'smooth'});
    pendingNewMessages = 0;
    newMessages.hidden = true;
  }

  function showNewMessageNotice() {
    pendingNewMessages += 1;
    newMessages.textContent = pendingNewMessages === 1 ? '新消息 ↓' : `${pendingNewMessages} 条新消息 ↓`;
    newMessages.hidden = false;
  }

  function insertAtCursor(value) {
    const start = input.selectionStart ?? input.value.length;
    const end = input.selectionEnd ?? input.value.length;
    if (input.value.length - (end - start) + value.length > input.maxLength) {
      showToast('消息已达到最大长度');
      return;
    }
    input.value = input.value.slice(0, start) + value + input.value.slice(end);
    const nextPosition = start + value.length;
    input.setSelectionRange(nextPosition, nextPosition);
    input.dispatchEvent(new Event('input'));
    input.focus();
  }

  function setEmojiPanel(open) {
    emojiPanel.hidden = !open;
    emojiButton.setAttribute('aria-expanded', String(open));
  }

  function updateNotificationButton() {
    if (!('Notification' in window)) {
      notificationButton.hidden = true;
      return;
    }
    notificationButton.classList.toggle('enabled', Notification.permission === 'granted');
    notificationButton.classList.toggle('denied', Notification.permission === 'denied');
    notificationButton.textContent = Notification.permission === 'denied' ? '🔕' : '🔔';
    notificationButton.title = Notification.permission === 'granted' ? '新消息通知已开启' :
      Notification.permission === 'denied' ? '浏览器已阻止通知，请在网站权限中修改' : '开启新消息通知';
  }

  function notifyIncomingMessage(message) {
    if (message.user_id === user.id || !document.hidden) return;
    unreadTitleCount += 1;
    document.title = `(${unreadTitleCount}) ${baseTitle}`;
    if ('Notification' in window && Notification.permission === 'granted') {
      const prefix = message.kind === 'image' ? '[图片] ' : '';
      const body = (prefix + (message.content || '')).trim() || '[图片]';
      const notification = new Notification(`${message.display_name} · ${user.room_name}`, {
        body: body.length > 100 ? `${body.slice(0, 100)}…` : body,
        tag: `chat-message-${message.id}`,
      });
      notification.onclick = () => {
        window.focus();
        notification.close();
      };
    }
  }

  function renderMessage(message, prepend = false) {
    if (document.querySelector(`[data-message-id="${message.id}"]`)) return;
    const mine = message.user_id === user.id;
    const article = document.createElement('article');
    article.className = `message${mine ? ' mine' : ''}${message.deleted ? ' deleted' : ''}`;
    article.dataset.messageId = message.id;
    article.dataset.message = JSON.stringify(message);
    const reply = message.reply_to_id ? `<div class="reply-preview"><b>${escapeHtml(message.reply_display_name || '消息')}</b> · ${escapeHtml((message.reply_kind === 'image' ? '[图片] ' : '') + (message.reply_content || ''))}</div>` : '';
    const dimensions = message.image_width && message.image_height ? ` width="${message.image_width}" height="${message.image_height}"` : '';
    const media = !message.deleted && message.kind === 'image' ? `<img src="/media/${encodeURIComponent(message.image_name)}" alt="${escapeHtml(message.content || '聊天图片')}" loading="lazy"${dimensions}>` : '';
    const text = message.deleted ? '此消息已删除' : escapeHtml(message.content);
    article.innerHTML = `
      <div class="message-avatar">${escapeHtml(message.display_name.slice(0, 1))}</div>
      <div class="message-main">
        ${mine ? '' : `<div class="message-name">${escapeHtml(message.display_name)}</div>`}
        <div class="bubble">${reply}${media}${text ? `<div class="bubble-text">${text}</div>` : ''}<div class="message-meta"><time>${formatTime(message.created_at)}</time></div></div>
      </div>
      ${message.deleted ? '' : `<div class="message-actions"><button data-action="reply" title="回复">↩</button>${mine ? '<button data-action="delete" title="删除">×</button>' : ''}</div>`}`;
    if (prepend) messagesEl.prepend(article); else messagesEl.append(article);
    oldestId = oldestId === null ? message.id : Math.min(oldestId, message.id);
  }

  async function loadMessages(before = null) {
    const oldHeight = pane.scrollHeight;
    const url = before ? `/api/messages?before=${before}` : '/api/messages';
    const response = await fetch(url);
    if (response.status === 401) return location.assign('/');
    const data = await response.json();
    data.items.slice().reverse().forEach((item) => renderMessage(item, true));
    loadMore.hidden = data.items.length < data.page_size;
    if (before) pane.scrollTop += pane.scrollHeight - oldHeight;
    else pane.scrollTop = pane.scrollHeight;
  }

  function connect() {
    const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
    socket = new WebSocket(`${protocol}//${location.host}/ws`);
    socket.onopen = () => {
      reconnectDelay = 1000;
      statusDot.classList.add('online');
      statusText.textContent = '已连接';
      sendButton.disabled = false;
    };
    socket.onmessage = ({data}) => {
      const event = JSON.parse(data);
      if (event.type === 'message') {
        const nearBottom = isNearBottom();
        renderMessage(event.message);
        if (nearBottom) pane.scrollTop = pane.scrollHeight;
        else showNewMessageNotice();
        notifyIncomingMessage(event.message);
      } else if (event.type === 'deleted') {
        const node = document.querySelector(`[data-message-id="${event.message_id}"]`);
        if (node) { node.classList.add('deleted'); node.querySelector('.bubble').innerHTML = '<div class="bubble-text">此消息已删除</div>'; node.querySelector('.message-actions')?.remove(); }
      } else if (event.type === 'typing' && event.user_id !== user.id) {
        if (event.active) typers.set(event.user_id, event.display_name); else typers.delete(event.user_id);
        typingEl.textContent = typers.size ? `${[...typers.values()].join('、')} 正在输入…` : '';
      } else if (event.type === 'presence') {
        const count = event.user_ids.length;
        statusText.textContent = `${count} 人在线`;
      } else if (event.type === 'error') showToast(event.message);
    };
    socket.onclose = (event) => {
      statusDot.classList.remove('online');
      statusText.textContent = event.code === 4401 ? '登录已失效' : '连接断开，正在重连…';
      sendButton.disabled = true;
      if (event.code === 4401) return setTimeout(() => location.assign('/'), 900);
      setTimeout(connect, reconnectDelay);
      reconnectDelay = Math.min(reconnectDelay * 1.8, 15000);
    };
  }

  function sendMessage() {
    const content = input.value.trim();
    if (!content || !socket || socket.readyState !== WebSocket.OPEN) return;
    socket.send(JSON.stringify({type:'message', content, reply_to_id: replyTo?.id || null}));
    input.value = '';
    input.style.height = '';
    cancelReply();
    socket.send(JSON.stringify({type:'typing', active:false}));
  }

  function setReply(message) {
    replyTo = message;
    el('replyName').textContent = message.display_name;
    el('replyText').textContent = messageText(message);
    el('replyBar').hidden = false;
    input.focus();
  }

  function cancelReply() { replyTo = null; el('replyBar').hidden = true; }

  function showToast(text) {
    const toast = el('toast');
    toast.textContent = text; toast.hidden = false;
    clearTimeout(showToast.timer); showToast.timer = setTimeout(() => toast.hidden = true, 2600);
  }

  async function uploadImage(file) {
    if (!file) return;
    if (file.size > config.maxImageMb * 1024 * 1024) return showToast(`图片不能超过 ${config.maxImageMb} MB`);
    const form = new FormData();
    form.append('image', file);
    form.append('caption', input.value.trim());
    if (replyTo) form.append('reply_to_id', replyTo.id);
    el('uploadProgress').hidden = false;
    try {
      const response = await fetch('/api/images', {method:'POST', body:form});
      if (!response.ok) { const body = await response.json(); throw new Error(body.detail || '图片发送失败'); }
      input.value = ''; cancelReply();
    } catch (error) { showToast(error.message); }
    finally { el('uploadProgress').hidden = true; imageInput.value = ''; }
  }

  sendButton.addEventListener('click', sendMessage);
  input.addEventListener('keydown', (event) => {
    if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); sendMessage(); }
  });
  input.addEventListener('input', () => {
    input.style.height = 'auto'; input.style.height = `${Math.min(input.scrollHeight, 130)}px`;
    if (socket?.readyState === WebSocket.OPEN) {
      socket.send(JSON.stringify({type:'typing', active:true}));
      clearTimeout(typingTimer); typingTimer = setTimeout(() => socket.send(JSON.stringify({type:'typing', active:false})), 1200);
    }
  });
  imageInput.addEventListener('change', () => uploadImage(imageInput.files[0]));
  emojis.forEach((emoji) => {
    const button = document.createElement('button');
    button.type = 'button';
    button.textContent = emoji;
    button.setAttribute('aria-label', `插入 ${emoji}`);
    button.addEventListener('click', () => insertAtCursor(emoji));
    emojiPanel.appendChild(button);
  });
  emojiButton.addEventListener('click', (event) => {
    event.stopPropagation();
    setEmojiPanel(emojiPanel.hidden);
  });
  emojiPanel.addEventListener('click', (event) => event.stopPropagation());
  document.addEventListener('click', () => setEmojiPanel(false));
  document.addEventListener('keydown', (event) => { if (event.key === 'Escape') setEmojiPanel(false); });
  notificationButton.addEventListener('click', async () => {
    if (!('Notification' in window)) return;
    if (Notification.permission === 'default') await Notification.requestPermission();
    updateNotificationButton();
  });
  document.addEventListener('visibilitychange', () => {
    if (!document.hidden) {
      unreadTitleCount = 0;
      document.title = baseTitle;
    }
  });
  loadMore.addEventListener('click', () => loadMessages(oldestId));
  newMessages.addEventListener('click', scrollToBottom);
  pane.addEventListener('scroll', () => {
    if (isNearBottom()) {
      pendingNewMessages = 0;
      newMessages.hidden = true;
    }
  }, {passive:true});
  el('cancelReply').addEventListener('click', cancelReply);
  messagesEl.addEventListener('click', async (event) => {
    const article = event.target.closest('.message');
    if (!article) return;
    const message = JSON.parse(article.dataset.message);
    if (event.target.matches('[data-action="reply"]')) setReply(message);
    if (event.target.matches('[data-action="delete"]') && confirm('删除这条消息？')) {
      const response = await fetch(`/api/messages/${message.id}`, {method:'DELETE'});
      if (!response.ok) showToast('删除失败');
    }
    if (event.target.matches('.bubble img')) { el('viewerImage').src = event.target.src; el('imageViewer').showModal(); }
  });
  el('closeViewer').addEventListener('click', () => el('imageViewer').close());
  el('imageViewer').addEventListener('click', (event) => { if (event.target === el('imageViewer')) el('imageViewer').close(); });

  loadMessages().catch(() => showToast('历史消息加载失败'));
  updateNotificationButton();
  connect();
})();
