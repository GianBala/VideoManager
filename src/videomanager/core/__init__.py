"""Núcleo da aplicação: lógica de mídia, sem nenhuma dependência de Qt.

Tudo neste pacote é testável sem interface e sem rede (exceto ``probe`` e
``downloader``, que falam com as plataformas). A regra é: ``core`` nunca importa
de ``ui`` nem de ``workers``.
"""
