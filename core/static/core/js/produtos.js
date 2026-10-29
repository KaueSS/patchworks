let modalTrigger = null;

function abrirModal(id, trigger) {
    const modal = document.getElementById(id);
    if (modal) {
        modalTrigger = trigger || document.activeElement;
        modal.style.display = 'flex';
        document.body.style.overflow = 'hidden';
        const closeButton = modal.querySelector('.btn-fechar');
        if (closeButton) closeButton.focus();
    }
}

function fecharModal(id) {
    const modal = document.getElementById(id);
    if (modal) {
        modal.style.display = 'none';
        document.body.style.overflow = '';
        if (modalTrigger && modalTrigger.isConnected) modalTrigger.focus();
        modalTrigger = null;
    }
}

function trocarImagem(produtoId, miniatura) {
    const imagemPrincipal = document.getElementById(`imagem-principal-${produtoId}`);
    if (imagemPrincipal) {
        imagemPrincipal.src = miniatura.src;
    }

    const galeria = miniatura.parentElement;
    const miniaturas = galeria.querySelectorAll('.galeria-img');

    miniaturas.forEach(function (img) {
        img.classList.remove('ativa');
    });

    miniatura.classList.add('ativa');
}

window.addEventListener('click', function (event) {
    const modais = document.querySelectorAll('.modal');

    modais.forEach(function (modal) {
        if (event.target === modal) {
            fecharModal(modal.id);
        }
    });
});

window.addEventListener('keydown', function (event) {
    if (event.key !== 'Escape') return;
    document.querySelectorAll('.modal').forEach(function (modal) {
        if (modal.style.display === 'flex') {
            fecharModal(modal.id);
        }
    });
});

function getCookie(name) {
    const value = `; ${document.cookie}`;
    const parts = value.split(`; ${name}=`);
    if (parts.length === 2) {
        return parts.pop().split(';').shift();
    }
    return '';
}

function onlyDigits(value) {
    return String(value || '').replace(/\D/g, '');
}

function formatCep(value) {
    const digits = onlyDigits(value).slice(0, 8);
    if (digits.length > 5) {
        return `${digits.slice(0, 5)}-${digits.slice(5)}`;
    }
    return digits;
}

function formatMoney(price, currency) {
    const n = Number(String(price).replace(',', '.'));
    if (Number.isNaN(n)) return `${currency || 'R$'} ${price}`;
    return n.toLocaleString('pt-BR', { style: 'currency', currency: 'BRL' });
}

function setFreteStatus(box, message, type) {
    const status = box.querySelector('[data-frete-status]');
    if (!status) return;
    status.hidden = !message;
    status.textContent = message || '';
    status.classList.remove('is-error', 'is-loading', 'is-ok', 'is-simulated');
    if (type) status.classList.add(type);
}

async function cotarFrete(box) {
    const produtoId = box.dataset.produtoId;
    const cepInput = box.querySelector('[data-frete-cep]');
    const qtdInput = box.querySelector('[data-frete-qtd]');
    const enderecoEl = box.querySelector('[data-frete-endereco]');
    const lista = box.querySelector('[data-frete-opcoes]');
    const btn = box.querySelector('[data-frete-btn]');

    const cep = onlyDigits(cepInput.value);
    const quantidade = Number(qtdInput.value || 1);
    const minima = Number(box.dataset.qtdMinima || 1);

    lista.innerHTML = '';
    enderecoEl.hidden = true;
    enderecoEl.textContent = '';
    box.querySelectorAll('.frete-calculo-info').forEach(function (el) {
        el.remove();
    });

    if (cep.length !== 8) {
        setFreteStatus(box, 'Informe um CEP válido com 8 dígitos.', 'is-error');
        return;
    }
    if (!Number.isFinite(quantidade) || quantidade < minima) {
        setFreteStatus(box, `Quantidade mínima: ${minima}.`, 'is-error');
        return;
    }

    setFreteStatus(box, 'Consultando frete...', 'is-loading');
    btn.disabled = true;

    try {
        const response = await fetch('/api/frete/cotar/', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': getCookie('csrftoken'),
            },
            body: JSON.stringify({
                produto_id: Number(produtoId),
                cep: cep,
                quantidade: quantidade,
            }),
        });

        const data = await response.json();

        if (!response.ok || !data.ok) {
            setFreteStatus(box, data.error || 'Não foi possível calcular o frete.', 'is-error');
            if (data.endereco) {
                enderecoEl.hidden = false;
                enderecoEl.textContent = [
                    data.endereco.logradouro,
                    data.endereco.bairro,
                    `${data.endereco.localidade}/${data.endereco.uf}`,
                ].filter(Boolean).join(' · ');
            }
            return;
        }

        if (data.endereco) {
            enderecoEl.hidden = false;
            enderecoEl.textContent = [
                data.endereco.logradouro,
                data.endereco.bairro,
                `${data.endereco.localidade}/${data.endereco.uf}`,
                data.endereco.cep,
            ].filter(Boolean).join(' · ');
        }

        if (!data.opcoes || !data.opcoes.length) {
            setFreteStatus(box, 'Nenhuma opção de frete disponível para este CEP.', 'is-error');
            return;
        }

        data.opcoes.forEach(function (opcao) {
            const li = document.createElement('li');
            li.className = 'frete-opcao';

            const prazo = opcao.delivery_time != null
                ? `${opcao.delivery_time} dia(s) útil(eis)`
                : 'Prazo sob consulta';

            const main = document.createElement('div');
            main.className = 'frete-opcao-main';

            const name = document.createElement('strong');
            name.textContent = `${opcao.company || 'Transportadora'} — ${opcao.name || 'Serviço'}`;

            const delivery = document.createElement('span');
            delivery.textContent = prazo;

            const price = document.createElement('div');
            price.className = 'frete-opcao-preco';
            price.textContent = formatMoney(opcao.price, opcao.currency);

            main.append(name, delivery);
            li.append(main, price);
            lista.appendChild(li);
        });

        setFreteStatus(
            box,
            data.simulado
                ? data.aviso
                : `${data.opcoes.length} opção(ões) encontrada(s).`,
            data.simulado ? 'is-simulated' : 'is-ok'
        );
        if (data.produto && data.produto.peso_total_kg != null) {
            const d = data.produto.dimensoes_unidade || {};
            const extra = document.createElement('p');
            extra.className = 'frete-calculo-info';
            extra.textContent =
                `Cálculo: ${data.produto.quantidade} un. · ` +
                `${d.height || '?'}×${d.width || '?'}×${d.length || '?'} cm/un · ` +
                `peso total ≈ ${String(data.produto.peso_total_kg).replace('.', ',')} kg`;
            lista.parentNode.insertBefore(extra, lista);
        }
    } catch (err) {
        setFreteStatus(box, 'Erro de conexão ao calcular o frete.', 'is-error');
    } finally {
        btn.disabled = false;
    }
}

document.addEventListener('DOMContentLoaded', function () {
    document.querySelectorAll('.produto-card[data-modal-id]').forEach(function (card) {
        card.addEventListener('click', function () {
            abrirModal(card.dataset.modalId, card);
        });
        card.addEventListener('keydown', function (event) {
            if (event.key === 'Enter' || event.key === ' ') {
                event.preventDefault();
                abrirModal(card.dataset.modalId, card);
            }
        });
    });

    document.querySelectorAll('[data-frete-box]').forEach(function (box) {
        const cepInput = box.querySelector('[data-frete-cep]');
        const btn = box.querySelector('[data-frete-btn]');

        if (cepInput) {
            cepInput.addEventListener('input', function () {
                cepInput.value = formatCep(cepInput.value);
            });
        }

        if (btn) {
            btn.addEventListener('click', function () {
                cotarFrete(box);
            });
        }
    });
});
