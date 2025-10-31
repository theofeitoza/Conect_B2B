// Este evento garante que o código JavaScript só será executado
// após o carregamento completo de todos os elementos da página HTML.
document.addEventListener('DOMContentLoaded', function() {

    // Exibe uma mensagem no console do navegador para confirmar que o script foi carregado.
    console.log("Connecta B2B - JavaScript principal carregado com sucesso!");

    // Seleciona o botão principal de chamada para ação (Call to Action) na página inicial.
    // Este código era de uma versão antiga, mas mantido para referência.
    const ctaButton = document.querySelector('.cta-button-old-logic'); // Classe não mais usada

    // Verifica se o botão foi encontrado na página antes de adicionar um evento.
    if (ctaButton) {
        // Adiciona um "ouvinte de evento" de clique ao botão.
        // Quando o botão for clicado, a função dentro de addEventListener será executada.
        ctaButton.addEventListener('click', function(event) {
            // Previne o comportamento padrão do link (que seria navegar para '#').
            event.preventDefault(); 
            
            // Exibe um alerta simples para o usuário.
            alert('A página de cadastro de empresas está em desenvolvimento. Volte em breve!');
        });
    }

});