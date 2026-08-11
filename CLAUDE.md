# CLAUDE.md

Contexto e convenções deste repositório. Leia antes de alterar qualquer coisa.

## O que é este projeto

Ferramenta de conciliação bancária automática, usada como **portfólio profissional** para captação de clientes de freelance em automação financeira. O público que vai ler este código é contador, gestor de PME e cliente potencial — não outro desenvolvedor.

Consequência prática: legibilidade e clareza do README valem tanto quanto a corretude do código.

## Arquitetura

| Arquivo | Responsabilidade |
|---|---|
| `src/conciliacao.py` | Motor geral: cascata de 6 estágios, extrato × razão |
| `src/repasses.py` | Repasses consolidados de plataforma, com dedução de comissão |
| `src/gerador_dados.py` | Dados sintéticos com gabarito conhecido |
| `src/relatorio.py` | Exportação Excel formatada |
| `app.py` | Demo Streamlit — conciliação geral |
| `app_repasses.py` | Demo Streamlit — repasses de plataforma |
| `main.py` | Execução via linha de comando |

## Princípios inegociáveis

**1. Determinismo.** Todo par conciliado precisa ser reproduzível e auditável, etiquetado com o método e o score que o produziram. Um contador precisa poder explicar por que duas linhas foram casadas. Nada de heurística opaca.

**2. Conservadorismo.** Na dúvida, deixar pendente em vez de conciliar errado. Falso negativo custa cinco minutos de conferência; falso positivo esconde erro no fechamento e destrói a confiança do cliente.

**3. Nenhum registro usado duas vezes.** Cada estágio retira do pool o que conciliou. Existe teste de invariante para isso — não o remova.

**4. Dados sempre sintéticos.** Nenhum dado real de cliente ou empregador entra neste repositório, em nenhuma circunstância, nem para teste local. O gerador com Faker cobre qualquer demonstração necessária.

**5. Português nos comentários e na documentação.** O cliente lê. Nomes de variáveis e funções também em português, mantendo o padrão existente.

## Convenções de código

- Type hints em assinaturas públicas; `from __future__ import annotations` no topo
- Dataclasses para parâmetros de configuração, nunca dicionários soltos
- Docstrings explicam **por que**, não o que — o código já diz o que faz
- pandas para dados tabulares; sem dependência nova sem necessidade real
- Toda função nova de lógica de negócio precisa de teste

## Testes

```bash
pytest -q                    # suíte completa (19 testes)
pytest tests/test_repasses.py -q
```

Duas categorias:
- **Gabarito**: o gerador injeta divergências conhecidas; o motor tem que recuperá-las
- **Invariantes**: nenhum registro duplicado, conservação de linhas, reprodutibilidade, soma dos lotes conferindo

Ao alterar o motor, rode a suíte antes e depois. Se um teste de gabarito quebrar, o motor regrediu — não ajuste o teste para passar.

## Deploy

Streamlit Community Cloud, apontando para `app_repasses.py` e `app.py` como apps separados do mesmo repositório. Requer repositório público e `requirements.txt` na raiz.

## Estado atual

Funcionando e testado: motor geral (98,1% de conciliação no cenário sintético), módulo de repasses (calibra a comissão da plataforma com erro abaixo de 1 p.p.), relatório Excel, duas demos, CLI, 19 testes passando.

Pendente: ver `BRIEFING-CLAUDE-CODE.md`.
