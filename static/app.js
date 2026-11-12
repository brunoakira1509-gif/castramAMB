(function () {
    var body = document.body;
    var toggle = document.getElementById('menu-toggle');
    var scrim = document.getElementById('scrim');
    if (toggle) toggle.addEventListener('click', function () { body.classList.toggle('menu-open'); });
    if (scrim) scrim.addEventListener('click', function () { body.classList.remove('menu-open'); });

    function pad(n) { return String(n).padStart(2, '0'); }
    var now = new Date();
    var iso = now.getFullYear() + '-' + pad(now.getMonth() + 1) + '-' + pad(now.getDate());

    // Valores padrão com base na data de hoje (relatórios)
    document.querySelectorAll('[data-today]').forEach(function (el) {
        var kind = el.dataset.today;
        el.value = kind === 'year' ? now.getFullYear() : kind === 'month' ? now.getMonth() + 1 : iso;
    });

    // Agendamento: apenas de segunda a sexta, a partir de hoje
    document.querySelectorAll('input[data-weekdays]').forEach(function (input) {
        input.min = iso;
        input.addEventListener('input', function () {
            var day = input.value ? new Date(input.value + 'T00:00:00').getDay() : 1;
            input.setCustomValidity(day === 0 || day === 6 ? 'Escolha um dia de segunda a sexta.' : '');
        });
    });

    // Envia o formulário ao trocar a seleção (substitui o onchange inline, bloqueado pela política de segurança)
    document.querySelectorAll('[data-autosubmit]').forEach(function (campo) {
        campo.addEventListener('change', function () { campo.form.submit(); });
    });

    // Pede confirmação antes de ações como cancelar um agendamento
    document.querySelectorAll('[data-confirm]').forEach(function (botao) {
        botao.addEventListener('click', function (evento) {
            if (!window.confirm(botao.dataset.confirm)) evento.preventDefault();
        });
    });

    // Busca de tutor enquanto digita: troca a lista de resultados sem recarregar a página
    document.querySelectorAll('[data-tutor-live]').forEach(function (campo) {
        var lista = document.getElementById(campo.dataset.target);
        var modelo = campo.dataset.href; // contém __ID__ no lugar do número do tutor
        var espera = null;
        var pedido = 0;

        function mostrar(tutores) {
            lista.textContent = '';
            if (!tutores.length) {
                var vazio = document.createElement('p');
                vazio.className = 'empty-inline';
                vazio.textContent = 'Nenhum tutor encontrado.';
                lista.appendChild(vazio);
                return;
            }
            tutores.forEach(function (t) {
                var link = document.createElement('a');
                link.className = 'pick';
                link.href = modelo.replace('__ID__', encodeURIComponent(t.id));
                var nome = document.createElement('span');
                nome.className = 'pick-name';
                nome.textContent = t.nome;
                var detalhe = document.createElement('span');
                detalhe.className = 'pick-meta';
                detalhe.textContent = t.detalhe;
                link.appendChild(nome);
                link.appendChild(detalhe);
                lista.appendChild(link);
            });
        }

        campo.addEventListener('input', function () {
            clearTimeout(espera);
            espera = setTimeout(function () {
                var este = ++pedido;
                fetch(campo.dataset.endpoint + '?q=' + encodeURIComponent(campo.value.trim()), {
                    headers: { 'Accept': 'application/json' }, credentials: 'same-origin'
                }).then(function (resposta) {
                    return resposta.ok ? resposta.json() : Promise.reject();
                }).then(function (dados) {
                    if (este === pedido) mostrar(dados.tutores);
                }).catch(function () { /* sem rede: a lista atual continua e o botão Buscar funciona */ });
            }, 200);
        });
    });
})();
