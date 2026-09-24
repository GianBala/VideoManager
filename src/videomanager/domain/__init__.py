"""Modelos e regras independentes de ferramentas externas."""

# Registra os textos do domínio antes de qualquer módulo daqui ser usado: quem
# importa um módulo do pacote passa primeiro por este arquivo.
from videomanager.domain import texts

__all__ = ["texts"]
