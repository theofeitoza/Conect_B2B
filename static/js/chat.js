document.addEventListener('DOMContentLoaded', function() {
    // 1. Obter dados dinâmicos do HTML
    const chatContainer = document.querySelector('.chat-container');
    const quoteId = chatContainer.dataset.quoteId;
    const currentCompanyName = chatContainer.dataset.companyName;
    const messagesDiv = document.getElementById('messages');
    const form = document.getElementById('message-form');
    const input = document.getElementById('message-input');
    const typingIndicator = document.getElementById('typing-indicator');
    const attachButton = document.getElementById('attach-button');
    const fileInput = document.getElementById('file-input');

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
        
        if (data.message) {
            const messageText = document.createElement('div');
            messageText.textContent = data.message;
            bubble.appendChild(messageText);
        }

        if (data.attachment_filename) {
            const attachmentLink = document.createElement('a');
            attachmentLink.href = `/uploads/chat/${data.attachment_filename}`;
            attachmentLink.textContent = data.attachment_filename;
            attachmentLink.target = '_blank';

            if (data.attachment_type === 'image') {
                const image = document.createElement('img');
                image.src = attachmentLink.href;
                image.style.maxWidth = '100%';
                image.style.borderRadius = '10px';
                attachmentLink.innerHTML = '';
                attachmentLink.appendChild(image);
            }
            bubble.appendChild(attachmentLink);
        }

        const messageInfo = document.createElement('div');
        messageInfo.classList.add('message-info');
        const time = data.timestamp.split(' ')[1] || data.timestamp;
        messageInfo.textContent = `${data.sender_name} - ${time}`;
        bubble.appendChild(messageInfo);

        messagesDiv.appendChild(bubble);
        messagesDiv.scrollTop = messagesDiv.scrollHeight;
    });
    
    // 6. Lógica de Envio (Mensagem e Arquivo)
    const sendMessage = (message, attachmentFilename) => {
        if (!message && !attachmentFilename) return;

        socket.emit('stop_typing', { quote_id: quoteId });
        clearTimeout(typingTimer);
        socket.emit('send_message', {
            quote_id: quoteId,
            message: message,
            attachment: attachmentFilename
        });
        input.value = '';
    };

    form.addEventListener('submit', function(e) {
        e.preventDefault();
        sendMessage(input.value.trim(), null);
    });

    attachButton.addEventListener('click', () => {
        fileInput.click();
    });

    fileInput.addEventListener('change', () => {
        const file = fileInput.files[0];
        if (!file) return;

        const formData = new FormData();
        formData.append('file', file);

        fetch('/chat/upload', {
            method: 'POST',
            body: formData
        })
        .then(response => response.json())
        .then(data => {
            if (data.filename) {
                sendMessage(null, data.filename);
            } else if (data.error) {
                alert(`Erro no upload: ${data.error}`);
            }
        })
        .catch(error => console.error('Erro no upload:', error));
        
        fileInput.value = ''; // Reseta o input para permitir o mesmo arquivo novamente
    });

    messagesDiv.scrollTop = messagesDiv.scrollHeight;
});