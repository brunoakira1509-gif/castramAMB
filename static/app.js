(function () {
    var body = document.body;
    var scrim = document.getElementById('scrim');
    document.querySelectorAll('[data-menu-toggle]').forEach(function (botao) {
        botao.addEventListener('click', function () { body.classList.toggle('menu-open'); });
    });
    if (scrim) scrim.addEventListener('click', function () { body.classList.remove('menu-open'); });

    function pad(n) { return String(n).padStart(2, '0'); }
    var now = new Date();
    var iso = now.getFullYear() + '-' + pad(now.getMonth() + 1) + '-' + pad(now.getDate());

    // Valores padrão com base na data de hoje (relatórios)
    document.querySelectorAll('[data-today]').forEach(function (el) {
        var kind = el.dataset.today;
        el.value = kind === 'year' ? now.getFullYear() : kind === 'month' ? now.getMonth() + 1
            : kind === 'month-start' ? now.getFullYear() + '-' + pad(now.getMonth() + 1) + '-01' : iso;
    });

    // No celular, ao tocar num dia do calendário a página rola direto para os detalhes do dia
    document.querySelectorAll('a.cal-day').forEach(function (dia) {
        dia.addEventListener('click', function () {
            if (window.matchMedia('(max-width: 860px)').matches && dia.href.indexOf('#') === -1) dia.href += '#dia';
        });
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


// Leitor de código de barras (celular): preenche o número do microchip com a câmera.
// Usa o BarcodeDetector do navegador (Chrome/Edge no Android). Exige HTTPS (ou localhost) e permissão da câmera.
(function () {
    var botao = document.querySelector('[data-scan-target]');
    if (!botao) return;
    var celular = window.matchMedia('(pointer: coarse)').matches || window.matchMedia('(max-width: 860px)').matches;
    var suportado = 'BarcodeDetector' in window && navigator.mediaDevices && navigator.mediaDevices.getUserMedia && window.isSecureContext;
    var msg = document.getElementById('scan-msg');
    function aviso(texto) { if (msg) { msg.textContent = texto; msg.hidden = !texto; } }
    if (!celular) return;
    botao.hidden = false;
    var alvo = document.getElementById(botao.dataset.scanTarget);
    var overlay = document.getElementById('scan-overlay');
    var video = document.getElementById('scan-video');
    var fluxo = null, ativo = false;

    function parar() {
        ativo = false;
        if (fluxo) { fluxo.getTracks().forEach(function (t) { t.stop(); }); fluxo = null; }
        video.srcObject = null;
        overlay.hidden = true;
    }

    function limpar(valor) { return String(valor || '').replace(/\s+/g, '').toUpperCase(); }

    botao.addEventListener('click', function () {
        aviso('');
        if (!suportado) {
            aviso(window.isSecureContext
                ? 'Este navegador não lê código de barras. Use o Chrome no Android ou digite o número.'
                : 'A câmera só funciona em conexão segura (HTTPS). Digite o número ou abra o sistema pelo endereço https.');
            return;
        }
        var pedido = BarcodeDetector.getSupportedFormats ? BarcodeDetector.getSupportedFormats() : Promise.resolve([]);
        pedido.then(function (formatos) {
            var desejados = ['code_128', 'code_39', 'ean_13', 'itf', 'codabar', 'data_matrix', 'qr_code'];
            var usar = formatos.length ? desejados.filter(function (f) { return formatos.indexOf(f) !== -1; }) : desejados;
            var detector = new BarcodeDetector(usar.length ? { formats: usar } : undefined);
            return navigator.mediaDevices.getUserMedia({ video: { facingMode: { ideal: 'environment' } }, audio: false })
                .then(function (stream) {
                    fluxo = stream; ativo = true;
                    video.srcObject = stream;
                    overlay.hidden = false;
                    return video.play();
                }).then(function () {
                    (function ler() {
                        if (!ativo) return;
                        detector.detect(video).then(function (codigos) {
                            var achado = codigos.map(function (c) { return limpar(c.rawValue); }).filter(Boolean)[0];
                            if (achado) {
                                alvo.value = achado.slice(0, alvo.maxLength > 0 ? alvo.maxLength : 20);
                                if (achado.length > (alvo.maxLength > 0 ? alvo.maxLength : 20)) aviso('O código lido é maior que um microchip. Confira o número antes de salvar.');
                                parar();
                                if (navigator.vibrate) navigator.vibrate(80);
                                alvo.focus();
                            } else { setTimeout(ler, 150); }
                        }).catch(function () { setTimeout(ler, 300); });
                    })();
                });
        }).catch(function (erro) {
            parar();
            aviso(erro && erro.name === 'NotAllowedError'
                ? 'Permissão da câmera negada. Libere a câmera nas configurações do navegador.'
                : 'Não foi possível abrir a câmera. Digite o número do microchip.');
        });
    });
    document.getElementById('scan-close').addEventListener('click', parar);
    document.addEventListener('keydown', function (e) { if (e.key === 'Escape' && ativo) parar(); });
})();
