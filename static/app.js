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
    document.querySelectorAll('select[data-autosubmit]').forEach(function (select) {
        select.addEventListener('change', function () { select.form.submit(); });
    });

    // Filtro de uma lista de seleção enquanto digita
    document.querySelectorAll('[data-filter-select]').forEach(function (input) {
        var select = document.getElementById(input.dataset.filterSelect);
        var placeholder = select.options.length && select.options[0].value === ''
            ? select.options[0].text : 'Selecione uma opção';
        var all = Array.from(select.options)
            .filter(function (o) { return o.value !== ''; })
            .map(function (o) { return { value: o.value, text: o.text }; });
        input.addEventListener('input', function () {
            var q = input.value.trim().toLowerCase().normalize('NFD').replace(/[\u0300-\u036f]/g, '');
            var current = select.value;
            var matches = all.filter(function (o) {
                return o.text.toLowerCase().normalize('NFD').replace(/[\u0300-\u036f]/g, '').indexOf(q) !== -1;
            });
            select.innerHTML = '';
            select.add(new Option(placeholder, ''));
            matches.forEach(function (o) {
                var opt = new Option(o.text, o.value);
                select.add(opt);
            });
            if (!matches.length && q) {
                var none = new Option('Nenhum tutor encontrado', '');
                none.disabled = true;
                select.add(none);
            }
            select.value = matches.some(function (o) { return o.value === current; }) ? current : '';
        });
    });
})();
