"""Ponte entre o núcleo (síncrono e bloqueante) e a interface Qt.

Regra que vale para todo este pacote: um worker **nunca** toca num widget. Toda
comunicação com a interface passa por sinais Qt, que são entregues na thread da
interface. Mexer em widget de outra thread não levanta erro na hora — corrompe a
tela ou derruba o processo bem depois, num lugar que não tem relação com a causa.
"""
