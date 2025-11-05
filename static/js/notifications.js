document.addEventListener('DOMContentLoaded', function() {
    // 1. Conectar ao Socket.IO (assim como em chat.js)
    // Presume-se que o script do Socket.IO já está carregado no HTML.
    const socket = io();

    // 2. Encontrar o link/ícone de notificação
    // Daremos um ID a ele nos templates HTML (veja o Passo 3)
    const notificationLink = document.getElementById('notification-link');
    if (!notificationLink) {
        console.warn('Elemento #notification-link não encontrado. Notificações em tempo real podem não funcionar.');
        return;
    }

    // 3. Ouvir por um evento de 'nova_notificacao' do servidor
    socket.on('new_notification', function(data) {
        console.log('Nova notificação recebida:', data);
        
        // 4. Encontrar o 'span' do contador (ou criar um se não existir)
        let countSpan = notificationLink.querySelector('span');
        
        if (!countSpan) {
            countSpan = document.createElement('span');
            // Estilos baseados no seu HTML (copiado de index.html)
            countSpan.style.position = 'absolute';
            countSpan.style.top = '0';
            countSpan.style.right = '-5px';
            countSpan.style.background = 'red';
            countSpan.style.color = 'white';
            countSpan.style.borderRadius = '50%';
            countSpan.style.padding = '2px 5px';
            countSpan.style.fontSize = '0.7rem';
            notificationLink.appendChild(countSpan);
        }
        
        // 5. Atualizar a contagem
        countSpan.textContent = data.unread_count;
        
        // Opcional: Adicionar um efeito visual (ex: um brilho)
        notificationLink.style.animation = 'pulse 0.5s 2';
    });

    // Adicionar CSS para a animação de pulso (opcional, mas bom para UX)
    const style = document.createElement('style');
    style.innerHTML = `
        @keyframes pulse {
            0% { transform: scale(1); }
            50% { transform: scale(1.2); }
            100% { transform: scale(1); }
        }
    `;
    document.head.appendChild(style);
});