from django.conf import settings
from django.db import models  # importa o módulo de modelos do Django (ORM)
from django.core.exceptions import ValidationError
from urllib.parse import quote
# Transforma a mensagem em formato válido para URL do zap
import re
# limpa o numero removendo - ( ) espaços etc


class MelhorEnvioToken(models.Model):
    """Token OAuth do Melhor Envio persistido no banco, fora do Admin."""

    payload = models.TextField('Dados OAuth')
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Token do Melhor Envio'
        verbose_name_plural = 'Token do Melhor Envio'

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

    def __str__(self):
        return 'Token do Melhor Envio'


class ConfiguracaoLoja(models.Model):
    """Origem da loja (CEP/endereço) — editável no Admin (registro único)."""

    cep = models.CharField(
        'CEP de origem',
        max_length=9,
        help_text='CEP de onde saem os envios (ex.: 07094-000). Usado na cotação Melhor Envio.',
    )
    endereco = models.CharField(
        'Endereço da loja',
        max_length=255,
        help_text='Endereço completo exibido e de referência da origem.',
    )
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Configuração da loja'
        verbose_name_plural = 'Configuração da loja'

    def __str__(self):
        return f'Loja · CEP {self.cep_formatado}'

    @property
    def cep_digitos(self) -> str:
        return re.sub(r'\D', '', str(self.cep or ''))

    @property
    def cep_formatado(self) -> str:
        digitos = self.cep_digitos
        if len(digitos) == 8:
            return f'{digitos[:5]}-{digitos[5:]}'
        return self.cep or ''

    def save(self, *args, **kwargs):
        self.pk = 1
        digitos = self.cep_digitos
        if len(digitos) == 8:
            self.cep = f'{digitos[:5]}-{digitos[5:]}'
        super().save(*args, **kwargs)

    @classmethod
    def get_solo(cls):
        obj, _ = cls.objects.get_or_create(
            pk=1,
            defaults={
                'cep': getattr(settings, 'STORE_CEP', '07094000'),
                'endereco': getattr(
                    settings,
                    'STORE_ADDRESS',
                    'Av. Dr. Timoteo Penteado, 1874 - Vila Hulda, Guarulhos - SP',
                ),
            },
        )
        return obj


class Categoria(models.Model):
    # para guardar o nome da categoria
    nome = models.CharField(max_length=100, unique=True)

    def __str__(self):
        return self.nome

    class Meta:
        verbose_name = "Categoria"
        verbose_name_plural = "Categorias"


class Produto(models.Model):
    # cria a tabela de produtos no banco

    nome = models.CharField(max_length=150)
    # nome do produto

    categoria = models.ForeignKey(
        Categoria,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='produtos'
    )
    # relação com a categoria

    codigo = models.CharField(max_length=50, unique=True)
    # SKU do produto

    descricao = models.TextField()
    # descrição detalhada

    preco = models.DecimalField(max_digits=8, decimal_places=2)
    # preço original do produto

    tem_desconto = models.BooleanField("Tem desconto?", default=False)
    # marca se o produto tem desconto

    preco_desconto = models.DecimalField(
        "Preço com desconto",
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True
    )
    # preço promocional / no pix

    imagem = models.ImageField(upload_to='produtos/')
    # imagem principal do produto

    medidas = models.CharField(max_length=100, blank=True)
    # medidas exibidas (texto livre)

    peso = models.CharField(max_length=50, blank=True)
    # peso exibido (texto livre)

    # Dimensões usadas na cotação Melhor Envio (cm / kg)
    altura_cm = models.PositiveIntegerField(
        "Altura (cm)",
        null=True,
        blank=True,
        help_text="Usado na cotação de frete (Melhor Envio)",
    )
    largura_cm = models.PositiveIntegerField(
        "Largura (cm)",
        null=True,
        blank=True,
        help_text="Usado na cotação de frete (Melhor Envio)",
    )
    comprimento_cm = models.PositiveIntegerField(
        "Comprimento (cm)",
        null=True,
        blank=True,
        help_text="Usado na cotação de frete (Melhor Envio)",
    )
    peso_kg = models.DecimalField(
        "Peso (kg)",
        max_digits=8,
        decimal_places=3,
        null=True,
        blank=True,
        help_text="Usado na cotação de frete (Melhor Envio)",
    )

    quantidade_minima = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="Exemplo: 100"
    )
    # quantidade mínima do pedido
    prazo_dias_uteis = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="Exemplo: 8"
    )
    # prazo de produção/entrega em dias úteis

    publicado_em = models.DateField(null=True, blank=True)
    # data de publicação

    whatsapp_numero = models.CharField(
        max_length=20,
        blank=True,
        null=True,
        help_text="Digite no formato: 5511999999999 (sem espaço ou hífen)"
    )
    # número que será usado para montar o link do WhatsApp

    criado_em = models.DateTimeField(auto_now_add=True)
    # salva automaticamente a data e hora quando o produto for criado

    def __str__(self):
        return self.nome
        # mostra o nome do produto

    def clean(self):
        """Evita salvar no Admin preços e medidas que quebram as cotações."""
        super().clean()
        errors = {}

        if self.tem_desconto:
            if self.preco_desconto is None:
                errors['preco_desconto'] = 'Informe o preço promocional.'
            elif self.preco is not None and self.preco_desconto >= self.preco:
                errors['preco_desconto'] = 'O preço promocional deve ser menor que o preço normal.'

        campos_frete = ('altura_cm', 'largura_cm', 'comprimento_cm', 'peso_kg')
        valores_frete = [getattr(self, campo) for campo in campos_frete]
        if any(valor is not None for valor in valores_frete):
            nomes = {
                'altura_cm': 'Altura',
                'largura_cm': 'Largura',
                'comprimento_cm': 'Comprimento',
                'peso_kg': 'Peso',
            }
            for campo, valor in zip(campos_frete, valores_frete):
                if valor is None:
                    errors[campo] = f'Informe {nomes[campo].lower()} para cotar o frete.'
                elif valor <= 0:
                    errors[campo] = f'{nomes[campo]} deve ser maior que zero.'

        if errors:
            raise ValidationError(errors)

    @property
    def whatsapp_link(self):
        if not self.whatsapp_numero:
            return "#"

        numero = re.sub(r'\D', '', self.whatsapp_numero)
        mensagem = f"Olá, tenho interesse no produto {self.nome}. Código: {self.codigo}"
        return f"https://wa.me/{numero}?text={quote(mensagem)}"

    @property
    def porcentagem_desconto(self):
        if (
            self.tem_desconto
            and self.preco_desconto is not None
            and self.preco is not None
            and self.preco > 0
        ):
            return int(((self.preco - self.preco_desconto) / self.preco) * 100)
        return 0

    @property
    def preco_seguro(self):
        """Valor unitário para insurance_value na cotação."""
        if self.tem_desconto and self.preco_desconto is not None:
            return self.preco_desconto
        return self.preco

    def dimensoes_unidade(self):
        """
        Dimensões/peso UNITÁRIOS para a cotação Melhor Envio (products[]).
        Não aplica mínimos de embalagem por peça — a API empacota a quantidade.
        """
        dimensions = (self.altura_cm, self.largura_cm, self.comprimento_cm)
        if any(value is None or value <= 0 for value in dimensions):
            raise ValueError('Informe altura, largura e comprimento maiores que zero.')
        if self.peso_kg is None or self.peso_kg <= 0:
            raise ValueError('Informe o peso do produto maior que zero.')

        height, width, length = (int(value) for value in dimensions)
        weight = float(self.peso_kg)
        return {
            'height': height,
            'width': width,
            'length': length,
            'weight': round(weight, 3),
        }

    def dimensoes_frete(self, quantidade=1):
        """
        Compatível com o fluxo antigo: retorna unidade real.
        quantidade é informativa (peso total estimado).
        """
        unidade = self.dimensoes_unidade()
        qtd = max(int(quantidade or 1), 1)
        return {
            **unidade,
            'quantity': qtd,
            'peso_total_kg': round(unidade['weight'] * qtd, 3),
        }

    class Meta:
        verbose_name = "Produto"
        verbose_name_plural = "Produtos"


class ProdutoImagem(models.Model):
    produto = models.ForeignKey(
        Produto,
        on_delete=models.CASCADE,
        related_name='imagens'
    )
    imagem = models.ImageField(upload_to='produtos/')

    def __str__(self):
        return f"Imagem de {self.produto.nome}"


class Avaliacao(models.Model):
    # cria uma tabela no banco chamada Avaliacao

    produto = models.ForeignKey(
        Produto,
        on_delete=models.CASCADE,
        related_name='avaliacoes',
        null=True,
        blank=True
    )
    # cada avaliação pode pertencer a um produto

    titulo = models.CharField(max_length=150)
    # título da avaliação

    descricao = models.TextField()
    # texto longo da avaliação

    imagem = models.ImageField(upload_to='avaliacoes/')
    # salva na pasta media/avaliacoes/

    link = models.URLField()
    # link externo da avaliação

    criado_em = models.DateTimeField(auto_now_add=True)
    # data/hora automática

    def __str__(self):
        return self.titulo

    class Meta:
        verbose_name = "Avaliação"
        verbose_name_plural = "Avaliações"
