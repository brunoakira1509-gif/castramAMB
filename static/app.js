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
        var all = Array.from(select.options).map(function (o) { return { value: o.value, text: o.text }; });
        input.addEventListener('input', function () {
            var q = input.value.trim().toLowerCase();
            var current = select.value;
            select.innerHTML = '';
            all.filter(function (o) { return !q || o.text.toLowerCase().indexOf(q) !== -1; }).forEach(function (o) {
                var opt = new Option(o.text, o.value);
                if (o.value === current) opt.selected = true;
                select.add(opt);
            });
            if (!select.options.length) {
                var none = new Option('Nenhum tutor encontrado', '');
                none.disabled = true;
                select.add(none);
                select.selectedIndex = -1;
            } else if (select.options.length === 1) {
                select.selectedIndex = 0;
            }
        });
    });
})();
