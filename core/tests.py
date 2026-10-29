from django.test import RequestFactory, SimpleTestCase, override_settings
from django.template.loader import render_to_string
import json
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
from decimal import Decimal

from django.test import override_settings

from core.models import Produto
from core.services.melhor_envio import calcular_frete_produtos, get_access_token
from core.services.viacep import ViaCepError

@override_settings(SESSION_ENGINE='django.contrib.sessions.backends.signed_cookies')
class MelhorEnvioCallbackTests(SimpleTestCase):
    def start_authorization(self):
        with patch('core.views.build_authorize_url', return_value='https://example.test/'):
            response = self.client.get('/api/melhorenvio/autorizar/', secure=True)
        self.assertEqual(response.status_code, 302)
        return self.client.session['melhorenvio_oauth_state']

    def test_callback_without_code_returns_bad_request(self):
        response = self.client.get('/api/melhorenvio/callback/', secure=True)

        self.assertEqual(response.status_code, 400)

    def test_callback_with_oauth_error_returns_bad_request(self):
        state = self.start_authorization()

        response = self.client.get(
            f'/api/melhorenvio/callback/?error=access_denied&state={state}', secure=True
        )

        self.assertEqual(response.status_code, 400)
        self.assertNotContains(response, 'access_denied', status_code=400)

    def test_callback_rejects_missing_or_mismatched_state(self):
        self.start_authorization()

        response = self.client.get(
            '/api/melhorenvio/callback/?code=some-code&state=wrong', secure=True
        )

        self.assertEqual(response.status_code, 400)

    @patch('core.views.exchange_code_for_token', return_value={'access_token': 'test-token'})
    def test_callback_accepts_matching_state(self, exchange_code):
        state = self.start_authorization()

        response = self.client.get(
            f'/api/melhorenvio/callback/?code=some-code&state={state}', secure=True
        )

        self.assertEqual(response.status_code, 200)
        exchange_code.assert_called_once_with('some-code')

    def test_authorize_generates_a_unique_state_and_stores_it(self):
        with patch('core.views.build_authorize_url') as build_url:
            build_url.side_effect = lambda state: f'https://example.test/?state={state}'

            first = self.client.get('/api/melhorenvio/autorizar/', secure=True)
            first_state = self.client.session['melhorenvio_oauth_state']
            second = self.client.get('/api/melhorenvio/autorizar/', secure=True)
            second_state = self.client.session['melhorenvio_oauth_state']

        self.assertEqual(first.status_code, 302)
        self.assertEqual(second.status_code, 302)
        self.assertNotEqual(first_state, 'patchworks')
        self.assertNotEqual(first_state, second_state)


class ProdutoShippingDataTests(SimpleTestCase):
    def test_freight_dimensions_require_real_package_data(self):
        produto = Produto(
            altura_cm=None,
            largura_cm=10,
            comprimento_cm=15,
            peso_kg=Decimal('0.250'),
        )

        with self.assertRaises(ValueError):
            produto.dimensoes_unidade()

    def test_discount_percentage_is_safe_when_regular_price_is_zero(self):
        produto = Produto(
            preco=Decimal('0.00'),
            preco_desconto=Decimal('1.00'),
            tem_desconto=True,
        )

        self.assertEqual(produto.porcentagem_desconto, 0)


class MelhorEnvioTokenRefreshTests(SimpleTestCase):
    @override_settings(
        MELHOR_ENVIO_CLIENT_ID='client-id-for-test',
        MELHOR_ENVIO_CLIENT_SECRET='client-secret-for-test',
        MELHOR_ENVIO_BASE_URL='https://sandbox.melhorenvio.com.br',
    )
    def test_expired_oauth_token_is_refreshed_and_saved(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            token_file = Path(temporary_directory) / 'token.json'
            token_file.write_text(json.dumps({
                'access_token': 'expired-access-token',
                'refresh_token': 'valid-refresh-token',
                'expires_at': 1,
            }), encoding='utf-8')

            response = Mock()
            response.status_code = 200
            response.json.return_value = {
                'access_token': 'fresh-access-token',
                'refresh_token': 'rotated-refresh-token',
                'expires_in': 3600,
                'token_type': 'Bearer',
            }

            with patch('core.services.melhor_envio.TOKEN_FILE', token_file), patch(
                'core.services.melhor_envio.requests.post', return_value=response
            ) as request:
                access_token = get_access_token()

            saved = json.loads(token_file.read_text(encoding='utf-8'))

        self.assertEqual(access_token, 'fresh-access-token')
        self.assertEqual(saved['refresh_token'], 'rotated-refresh-token')
        self.assertGreater(saved['expires_at'], 1)
        self.assertEqual(request.call_args.kwargs['data']['grant_type'], 'refresh_token')

    @override_settings(
        MELHOR_ENVIO_CLIENT_ID='client-id-for-test',
        MELHOR_ENVIO_CLIENT_SECRET='client-secret-for-test',
        MELHOR_ENVIO_BASE_URL='https://sandbox.melhorenvio.com.br',
    )
    def test_unauthenticated_quote_refreshes_token_and_retries_once(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            token_file = Path(temporary_directory) / 'token.json'
            token_file.write_text(json.dumps({
                'access_token': 'expired-access-token',
                'refresh_token': 'valid-refresh-token',
                'expires_at': 4_000_000_000,
            }), encoding='utf-8')

            unauthorized = Mock(status_code=401)
            unauthorized.json.return_value = {'message': 'Unauthenticated.'}
            refreshed = Mock(status_code=200)
            refreshed.json.return_value = {
                'access_token': 'fresh-access-token',
                'refresh_token': 'rotated-refresh-token',
                'expires_in': 3600,
            }
            quote = Mock(status_code=200)
            quote.json.return_value = [{
                'id': 1,
                'name': 'PAC',
                'price': '20.50',
                'company': {'name': 'Correios'},
            }]

            with patch('core.services.melhor_envio.TOKEN_FILE', token_file), patch(
                'core.services.melhor_envio._cep_origem_loja', return_value='07094000'
            ), patch(
                'core.services.melhor_envio.requests.post',
                side_effect=[unauthorized, refreshed, quote],
            ) as request:
                options = calcular_frete_produtos(
                    cep_destino='01001000',
                    products=[{
                        'id': 'TESTE',
                        'width': 10,
                        'height': 10,
                        'length': 10,
                        'weight': 0.5,
                        'quantity': 1,
                    }],
                )

        self.assertEqual(len(options), 1)
        self.assertEqual(request.call_count, 3)
        self.assertEqual(
            request.call_args.kwargs['headers']['Authorization'],
            'Bearer fresh-access-token',
        )


class FreightDemoModeTests(SimpleTestCase):
    @override_settings(MELHOR_ENVIO_SIMULATE_FREIGHT=True)
    @patch('core.views.calcular_frete_produtos')
    @patch('core.views.consultar_cep')
    @patch('core.views.ConfiguracaoLoja.get_solo')
    @patch('core.views.get_object_or_404')
    def test_demo_mode_returns_labeled_options_without_external_freight_calls(
        self, get_product, get_store, lookup_cep, calculate_freight
    ):
        product = SimpleNamespace(
            id=1,
            codigo='DEMO-1',
            nome='Produto demonstrativo',
            quantidade_minima=1,
            preco_seguro=Decimal('35.00'),
            dimensoes_unidade=lambda: {
                'width': 10,
                'height': 8,
                'length': 12,
                'weight': 0.25,
            },
        )
        get_product.return_value = product
        get_store.return_value = SimpleNamespace(cep_digitos='07094000')
        lookup_cep.return_value = {
            'cep': '01001-000',
            'logradouro': 'Praça da Sé',
            'bairro': 'Sé',
            'localidade': 'São Paulo',
            'uf': 'SP',
        }
        calculate_freight.return_value = []

        response = self.client.post(
            '/api/frete/cotar/',
            data=json.dumps({'produto_id': 1, 'cep': '01001000', 'quantidade': 1}),
            content_type='application/json',
            secure=True,
        )

        body = response.json()
        self.assertEqual(response.status_code, 200)
        self.assertIs(body.get('simulado'), True)
        self.assertIn('SIMULAÇÃO', body.get('aviso', '').upper())
        self.assertTrue(body.get('opcoes'))
        self.assertEqual(body['endereco']['localidade'], 'São Paulo')
        lookup_cep.assert_called_once_with('01001000')
        calculate_freight.assert_not_called()

    @override_settings(MELHOR_ENVIO_SIMULATE_FREIGHT=True)
    @patch('core.views.calcular_frete_produtos')
    @patch('core.views.consultar_cep', side_effect=ViaCepError('ViaCEP indisponível.', 502))
    @patch('core.views.ConfiguracaoLoja.get_solo')
    @patch('core.views.get_object_or_404')
    def test_demo_quote_survives_a_temporary_viacep_outage(
        self, get_product, get_store, lookup_cep, calculate_freight
    ):
        product = SimpleNamespace(
            id=1,
            codigo='DEMO-1',
            nome='Produto demonstrativo',
            quantidade_minima=1,
            preco_seguro=Decimal('35.00'),
            dimensoes_unidade=lambda: {
                'width': 10,
                'height': 8,
                'length': 12,
                'weight': 0.25,
            },
        )
        get_product.return_value = product
        get_store.return_value = SimpleNamespace(cep_digitos='07094000')

        response = self.client.post(
            '/api/frete/cotar/',
            data=json.dumps({'produto_id': 1, 'cep': '01001000', 'quantidade': 1}),
            content_type='application/json',
            secure=True,
        )

        body = response.json()
        self.assertEqual(response.status_code, 200)
        self.assertIs(body.get('simulado'), True)
        self.assertIsNone(body.get('endereco'))
        self.assertIn('ViaCEP', body.get('aviso', ''))
        self.assertTrue(body.get('opcoes'))
        calculate_freight.assert_not_called()

    @override_settings(MELHOR_ENVIO_SIMULATE_FREIGHT=True)
    @patch('core.views.consultar_cep', side_effect=ViaCepError('CEP não encontrado.', 404))
    @patch('core.views.ConfiguracaoLoja.get_solo')
    @patch('core.views.get_object_or_404')
    def test_demo_quote_rejects_a_cep_not_found_by_viacep(
        self, get_product, get_store, lookup_cep
    ):
        product = SimpleNamespace(
            id=1,
            codigo='DEMO-1',
            nome='Produto demonstrativo',
            quantidade_minima=1,
            preco_seguro=Decimal('35.00'),
            dimensoes_unidade=lambda: {
                'width': 10,
                'height': 8,
                'length': 12,
                'weight': 0.25,
            },
        )
        get_product.return_value = product
        get_store.return_value = SimpleNamespace(cep_digitos='07094000')

        response = self.client.post(
            '/api/frete/cotar/',
            data=json.dumps({'produto_id': 1, 'cep': '99999999', 'quantidade': 1}),
            content_type='application/json',
            secure=True,
        )

        self.assertEqual(response.status_code, 404)
        self.assertFalse(response.json().get('ok'))


class StoreContactPageTests(SimpleTestCase):
    @patch('core.views.ConfiguracaoLoja.get_solo')
    def test_contact_page_uses_configured_address_without_example_contacts(self, get_store):
        get_store.return_value = SimpleNamespace(
            endereco='Rua de demonstração, 10 — Guarulhos/SP',
            cep_formatado='07000-000',
        )

        response = self.client.get('/contato/', secure=True, HTTP_HOST='127.0.0.1')

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Rua de demonstração, 10 — Guarulhos/SP')
        self.assertContains(response, '07000-000')
        self.assertNotContains(response, '99999-5882')
        self.assertNotContains(response, 'Juliana.xxx@xxxxx.com')
        self.assertContains(response, 'Instagram')


class ProductAccessibilityMarkupTests(SimpleTestCase):
    def render_product_page(self):
        image = SimpleNamespace(url='/media/produto-principal.jpg')
        additional_image = SimpleNamespace(imagem=SimpleNamespace(url='/media/produto-detalhe.jpg'))
        product = SimpleNamespace(
            id=1,
            nome='Produto de demonstração',
            imagem=image,
            imagens=SimpleNamespace(all=lambda: [additional_image]),
            tem_desconto=False,
            preco=Decimal('25.00'),
            quantidade_minima=1,
            prazo_dias_uteis=5,
            descricao='Descrição de demonstração.',
            medidas='10 × 8 × 12 cm',
            peso='250 g',
            codigo='DEMO-1',
            publicado_em=None,
            whatsapp_numero='',
        )
        request = RequestFactory().get('/produtos/')
        return render_to_string(
            'core/produtos.html',
            {
                'produtos': [product],
                'categorias': [],
                'busca': '',
                'categoria_id': '',
                'loja': SimpleNamespace(endereco='Rua de demonstração', cep_formatado='07000-000'),
            },
            request=request,
        )

    def test_freight_status_uses_a_polite_live_region(self):
        html = self.render_product_page()

        self.assertIn('role="status"', html)
        self.assertIn('aria-live="polite"', html)
        self.assertIn('aria-atomic="true"', html)

    def test_gallery_thumbnails_are_keyboard_operable_buttons(self):
        html = self.render_product_page()

        self.assertIn('class="galeria-thumb"', html)
        self.assertIn('aria-pressed="true"', html)
        self.assertIn('aria-label="Ver imagem', html)
