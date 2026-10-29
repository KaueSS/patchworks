"""Valores ilustrativos para demonstrações sem acesso ao Melhor Envio."""

from __future__ import annotations


_REGIAO_POR_CEP = {
    '0': 'sudeste', '1': 'sudeste', '2': 'sudeste', '3': 'sudeste',
    '4': 'nordeste', '5': 'nordeste',
    '6': 'norte',
    '7': 'centro-oeste',
    '8': 'sul', '9': 'sul',
}

_FATOR_REGIONAL = {
    'sudeste': 1.0,
    'sul': 1.18,
    'centro-oeste': 1.30,
    'nordeste': 1.42,
    'norte': 1.75,
}


def simular_opcoes_frete(*, cep_origem: str, cep_destino: str, dimensoes: dict, quantidade: int):
    origem = ''.join(ch for ch in str(cep_origem) if ch.isdigit())
    destino = ''.join(ch for ch in str(cep_destino) if ch.isdigit())
    if len(origem) != 8 or len(destino) != 8:
        raise ValueError('Para simular, informe CEPs com 8 dígitos.')
    if quantidade < 1:
        raise ValueError('A quantidade deve ser pelo menos 1.')

    try:
        peso_total = float(dimensoes['weight']) * quantidade
        volume_total_litros = (
            float(dimensoes['height'])
            * float(dimensoes['width'])
            * float(dimensoes['length'])
            * quantidade
            / 1000
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError('Dimensões e peso são necessários para simular o frete.') from exc

    if peso_total <= 0 or volume_total_litros <= 0:
        raise ValueError('Dimensões e peso devem ser maiores que zero.')

    regiao_origem = _REGIAO_POR_CEP[origem[0]]
    regiao_destino = _REGIAO_POR_CEP[destino[0]]
    diferenca_regional = abs(
        _FATOR_REGIONAL[regiao_origem] - _FATOR_REGIONAL[regiao_destino]
    )
    base = 18 + (diferenca_regional * 22)
    adicional_volume = max(0, volume_total_litros - 10) * 0.12
    pac = round(base + (peso_total * 4.5) + adicional_volume, 2)
    sedex = round((pac * 1.5) + 7, 2)
    dias_adicionais = round(diferenca_regional * 5)

    return [
        {
            'id': 'demo-pac',
            'name': 'PAC ilustrativo',
            'company': 'Simulação local',
            'price': f'{pac:.2f}',
            'currency': 'BRL',
            'delivery_time': 4 + dias_adicionais,
        },
        {
            'id': 'demo-sedex',
            'name': 'SEDEX ilustrativo',
            'company': 'Simulação local',
            'price': f'{sedex:.2f}',
            'currency': 'BRL',
            'delivery_time': 2 + dias_adicionais,
        },
    ]
