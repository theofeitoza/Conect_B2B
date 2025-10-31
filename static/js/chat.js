document.addEventListener('DOMContentLoaded', function() {
    // 1. Obter dados dinâmicos do HTML
    const chatContainer = document.querySelector('.chat-container');
    const quoteId = chatContainer.dataset.quoteId;
    const currentCompanyName = chatContainer.dataset.companyName;
    const messagesDiv = document.getElementById('messages');
    const form = document.getElementById('message-form');
    const input = document.getElementById('message-input');
    const typingIndicator = document.getElementById('typing-indicator');

    if (!chatContainer || !quoteId || !currentCompanyName) {
        console.error("Erro: Não foi possível carregar os dados do chat.");
        return;
    }

    // 2. Conectar ao servidor Socket.IO
    const socket = io();
    let typingTimer;
    const TYPING_TIMER_LENGTH = 1500; // 1.5 segundos

    // 3. Lógica de "Digitando..."
    input.addEventListener('input', () => {
        clearTimeout(typingTimer);
        socket.emit('typing', { quote_id: quoteId });
        typingTimer = setTimeout(() => {
            socket.emit('stop_typing', { quote_id: quoteId });
        }, TYPING_TIMER_LENGTH);
    });

    socket.on('user_typing', (data) => {
        if (data.sender_name !== currentCompanyName) {
            typingIndicator.textContent = `${data.sender_name} está digitando...`;
        }
    });

    socket.on('user_stopped_typing', (data) => {
        typingIndicator.textContent = '';
    });

    // 4. Ao conectar, entrar na sala específica desta cotação
    socket.on('connect', function() {
        socket.emit('join', { quote_id: quoteId });
    });

    // 5. Ouvir por novas mensagens do servidor
    socket.on('message', function(data) {
        typingIndicator.textContent = ''; // Limpa o indicador ao receber uma mensagem
        const isSentByMe = data.sender_name === currentCompanyName;
        const bubble = document.createElement('div');
        bubble.classList.add('message-bubble');
        bubble.classList.add(isSentByMe ? 'sent' : 'received');
        const messageText = document.createElement('div');
        messageText.textContent = data.message;
        const messageInfo = document.createElement('div');
        messageInfo.classList.add('message-info');
        const time = data.timestamp.split(' ')[1] || data.timestamp;
        messageInfo.textContent = `${data.sender_name} - ${time}`;
        bubble.appendChild(messageText);
        bubble.appendChild(messageInfo);
        messagesDiv.appendChild(bubble);
        messagesDiv.scrollTop = messagesDiv.scrollHeight;
    });

    // 6. Enviar uma mensagem quando o formulário é submetido
    form.addEventListener('submit', function(e) {
        e.preventDefault();
        if (input.value.trim()) {
            socket.emit('stop_typing', { quote_id: quoteId }); // Garante que o "digitando" pare
            clearTimeout(typingTimer);
            socket.emit('send_message', {
                quote_id: quoteId,
                message: input.value.trim()
            });
            input.value = '';
        }
    });

    messagesDiv.scrollTop = messagesDiv.scrollHeight;
});