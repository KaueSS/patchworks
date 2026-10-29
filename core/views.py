import json
import secrets

from django.conf import settings
from django.http import HttpResponse, HttpResponseBadRequest, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_GET, require_POST

from .models import Avaliacao, ConfiguracaoLoja, Produto, Categoria
from .services.melhor_envio import (
    MelhorEnvioError,
    build_authorize_url,
    calcular_frete_produtos,
    exchange_code_for_token,
)
from .services.viacep import ViaCepError, consultar_cep
from .services.frete_simulado import simular_opcoes_frete


def home(request):
    return render(request, 'core/home.html', {'loja': ConfiguracaoLoja.get_solo()})


def avaliacoes(request):
    avaliacoes = Avaliacao.objects.select_related('produto').order_by('-criado_em')
    return render(request, 'core/avaliacoes.html', {
        'avaliacoes': avaliacoes,
        'loja': ConfiguracaoLoja.get_solo(),
    })


@ensure_csrf_cookie
def produtos(request):
    busca = request.GET.get('busca', '').strip()[:120]
    categoria_raw = request.GET.get('categoria', '').strip()
    categoria_id = categoria_raw if categoria_raw.isdecimal() else ''

    produtos = Produto.objects.select_related('categoria').prefetch_related('imagens').order_by(
        '-criado_em'
    )

    if busca:
        produtos = produtos.filter(nome__icontains=busca)

    if categoria_id:
        produtos = produtos.filter(categoria_id=categoria_id)

    categorias = Categoria.objects.all().order_by('nome')
    loja = ConfiguracaoLoja.get_solo()

    return render(request, 'core/produtos.html', {
        'produtos': produtos,
        'categorias': categorias,
        'busca': busca,
        'categoria_id': categoria_id,
        'loja': loja,
    })


def contato(request):
    return render(request, 'core/contato.html', {'loja': ConfiguracaoLoja.get_solo()})


@require_GET
def api_consultar_cep(request):
    cep = request.GET.get('cep', '')
    try:
        endereco = consultar_cep(cep)
        return JsonResponse({'ok': True, 'endereco': endereco})
    except ViaCepError as exc:
        return JsonResponse(
            {'ok': False, 'error': exc.message},
            status=exc.status_code or 400,
        )


@require_POST
def api_cotar_frete(request):
    try:
        payload = json.loads(request.body.decode('utf-8') or '{}')
    except json.JSONDecodeError:
        return JsonResponse({'ok': False, 'error': 'JSON inválido.'}, status=400)

    produto_id = payload.get('produto_id')
    cep_destino = payload.get('cep', '')
    quantidade = payload.get('quantidade', 1)

    if not produto_id:
        return JsonResponse({'ok': False, 'error': 'produto_id é obrigatório.'}, status=400)

    try:
        quantidade = int(quantidade)
    except (TypeError, ValueError):
        return JsonResponse({'ok': False, 'error': 'Quantidade inválida.'}, status=400)

    if quantidade < 1:
        return JsonResponse({'ok': False, 'error': 'Quantidade deve ser pelo menos 1.'}, status=400)

    produto = get_object_or_404(Produto, pk=produto_id)

    if produto.quantidade_minima and quantidade < produto.quantidade_minima:
        return JsonResponse(
            {
                'ok': False,
                'error': f'Quantidade mínima deste produto é {produto.quantidade_minima}.',
            },
            status=400,
        )

    try:
        dims = produto.dimensoes_unidade()
    except ValueError as exc:
        return JsonResponse({'ok': False, 'error': str(exc)}, status=400)

    loja = ConfiguracaoLoja.get_solo()
    simulado = settings.MELHOR_ENVIO_SIMULATE_FREIGHT
    endereco = None

    if simulado:
        aviso_cep = ''
        try:
            endereco = consultar_cep(cep_destino)
        except ViaCepError as exc:
            if exc.status_code != 502:
                return JsonResponse(
                    {'ok': False, 'error': exc.message},
                    status=exc.status_code or 400,
                )
            aviso_cep = 'ViaCEP indisponível; o endereço não foi validado.'

        try:
            opcoes = simular_opcoes_frete(
                cep_origem=loja.cep_digitos,
                cep_destino=cep_destino,
                dimensoes=dims,
                quantidade=quantidade,
            )
        except ValueError as exc:
            return JsonResponse({'ok': False, 'error': str(exc)}, status=400)
    else:
        try:
            endereco = consultar_cep(cep_destino)
        except ViaCepError as exc:
            return JsonResponse(
                {'ok': False, 'error': exc.message},
                status=exc.status_code or 400,
            )

        insurance = float(produto.preco_seguro)
        products = [{
            'id': str(produto.codigo or produto.id),
            'width': dims['width'],
            'height': dims['height'],
            'length': dims['length'],
            'weight': dims['weight'],
            'insurance_value': insurance,
            'quantity': quantidade,
        }]

        try:
            opcoes = calcular_frete_produtos(
                cep_destino=cep_destino,
                products=products,
            )
        except MelhorEnvioError as exc:
            status = exc.status_code if exc.status_code and 400 <= exc.status_code < 600 else 502
            return JsonResponse(
                {
                    'ok': False,
                    'error': exc.message,
                    'details': exc.details,
                    'endereco': endereco,
                },
                status=status,
            )

    return JsonResponse({
        'ok': True,
        'simulado': simulado,
        'aviso': (
            'SIMULAÇÃO: preço e prazo ilustrativos; não são uma cotação do Melhor Envio.'
            + (f' {aviso_cep}' if simulado and aviso_cep else '')
            if simulado else ''
        ),
        'endereco': endereco,
        'origem_cep': loja.cep_digitos,
        'produto': {
            'id': produto.id,
            'nome': produto.nome,
            'codigo': produto.codigo,
            'quantidade': quantidade,
            'dimensoes_unidade': dims,
            'peso_total_kg': round(dims['weight'] * quantidade, 3),
        },
        'opcoes': opcoes,
    })


@require_GET
def melhorenvio_autorizar(request):
    """Redireciona para o OAuth do Melhor Envio (sandbox/produção)."""
    state = secrets.token_urlsafe(32)
    request.session['melhorenvio_oauth_state'] = state
    try:
        url = build_authorize_url(state=state)
    except MelhorEnvioError as exc:
        return HttpResponse(
            '<h1>Configuração do Melhor Envio incompleta</h1>'
            '<p>Confira as credenciais e o endereço de retorno configurados no ambiente local.</p>',
            status=exc.status_code or 503,
        )
    return redirect(url)


@require_GET
def melhorenvio_callback(request):
    """Recebe o ?code= do Melhor Envio e troca por access_token."""
    expected_state = request.session.pop('melhorenvio_oauth_state', None)
    received_state = request.GET.get('state')
    if not expected_state or not received_state or not secrets.compare_digest(
        expected_state, received_state
    ):
        return HttpResponseBadRequest(
            '<h1>Retorno de autorização inválido</h1><p>Inicie a autorização novamente pelo site.</p>'
        )

    error = request.GET.get('error')
    if error:
        return HttpResponseBadRequest(
            '<h1>Autorização não concluída</h1>'
            '<p>O Melhor Envio não autorizou a conexão. Tente novamente pelo site.</p>'
        )

    code = request.GET.get('code')
    if not code:
        return HttpResponseBadRequest('<h1>Callback sem code</h1><p>Parâmetro code não encontrado.</p>')

    try:
        data = exchange_code_for_token(code)
    except MelhorEnvioError as exc:
        return HttpResponse(
            '<h1>Falha ao concluir a autorização</h1>'
            '<p>Confira a configuração e tente novamente. Nenhuma credencial foi exibida.</p>',
            status=exc.status_code or 502,
        )

    expires = data.get('expires_in', '?')
    return HttpResponse(
        '<h1>Token Melhor Envio salvo</h1>'
        f'<p>access_token obtido com sucesso (expires_in={expires}s).</p>'
        '<p>Arquivo: <code>melhorenvio_token.json</code></p>'
        '<p><a href="/produtos/">Voltar aos produtos e testar a cotação</a></p>'
    )
