function createScanErrorAction(action) {
    var button = document.createElement('button');
    button.type = 'button';
    button.className = 'scan-error-action' + (action.primary ? ' scan-error-action--primary' : '');
    button.textContent = action.label || '重试';
    button.onclick = function() {
        if (typeof action.onClick === 'function') action.onClick();
    };
    return button;
}

function showScanError(list, message, actions) {
    list.innerHTML = '';
    if (list.id === 'scan-list') {
        var summary = document.getElementById('scan-result-summary');
        if (summary) summary.innerHTML = '';
    }
    var panel = document.createElement('div');
    panel.className = 'scan-error';
    var title = document.createElement('strong');
    title.textContent = '请求失败';
    var detail = document.createElement('span');
    detail.textContent = message || '未知错误';
    panel.appendChild(title);
    panel.appendChild(detail);
    if (actions && actions.length) {
        var actionRow = document.createElement('div');
        actionRow.className = 'scan-error-actions';
        actions.forEach(function(action) {
            actionRow.appendChild(createScanErrorAction(action));
        });
        panel.appendChild(actionRow);
    }
    list.appendChild(panel);
}
