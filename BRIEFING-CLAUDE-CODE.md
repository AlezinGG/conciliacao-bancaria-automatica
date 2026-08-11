# Briefing para o Claude Code

Documento de transferência. Contém o contexto, as tarefas pendentes e os prompts prontos para colar.

---

## Situação

Projeto de portfólio para captação de clientes freelance. Existe uma oportunidade concreta e urgente: um cliente (administradora de imóveis por temporada) publicou projeto de conciliação de lotes de pagamento do Airbnb no sistema Nibo. A proposta já está escrita, mas depende de duas coisas:

1. O projeto publicado no GitHub e a demo no ar no Streamlit
2. Uma funcionalidade que a proposta promete e o código ainda não tem: **rateio por imóvel e proprietário**

O prazo é curto. Prioridade: publicar primeiro, melhorar depois.

---

## Prompt 1 — Organizar, validar e publicar

Cole isto na primeira mensagem do Claude Code, com a pasta do projeto aberta:

> Estou preparando este projeto para publicar no GitHub e no Streamlit Community Cloud. Ele é meu portfólio para captar clientes de automação financeira, e tem um cliente esperando a demo.
>
> Leia o CLAUDE.md antes de começar — ele tem as convenções do projeto.
>
> Preciso que você:
>
> 1. Verifique se a estrutura de pastas está correta (src/ e tests/ com os arquivos certos, src/\_\_init\_\_.py existindo). Se os arquivos estiverem soltos na raiz, rode o setup_projeto.py ou organize manualmente.
> 2. Instale as dependências e rode a suíte de testes. Devem passar 19 testes.
> 3. Verifique se app.py e app_repasses.py sobem sem erro de import.
> 4. Confira o README: substitua os placeholders `<seu-usuario>` pelo meu usuário do GitHub, que vou informar, e me avise de qualquer link quebrado ou informação desatualizada.
> 5. Inicialize o repositório Git, faça o primeiro commit com mensagem descritiva e me oriente no passo a passo para criar o repositório remoto e dar push.
>
> Me pergunte o que precisar antes de assumir qualquer coisa. Não altere a lógica do motor nesta etapa.

---

## Prompt 2 — Implementar o rateio por imóvel e proprietário

Depois que estiver publicado:

> Preciso adicionar uma funcionalidade ao módulo src/repasses.py.
>
> **Contexto de negócio:** uma administradora de imóveis por temporada recebe do Airbnb créditos consolidados — um único depósito cobrindo várias reservas, de imóveis e proprietários diferentes, já líquido de comissão. O módulo hoje reconstrói quais reservas compõem cada crédito e calcula a comissão implícita. Falta o passo seguinte: distribuir o valor líquido entre imóveis e proprietários.
>
> **O que implementar:**
>
> - Uma função que, a partir do resultado de `ConciliadorRepasses.conciliar()` e do razão original (que tem as colunas `imovel` e `proprietario`), produza um DataFrame com uma linha por reserva contendo: id do repasse, data do crédito, imóvel, proprietário, valor bruto da reserva, comissão rateada proporcionalmente ao bruto, e valor líquido atribuído.
> - Uma agregação por proprietário e outra por imóvel, para conferência de repasse.
> - Garantia de fechamento: a soma dos líquidos rateados de um lote tem que igualar o valor creditado, com tolerância de centavos. Trate a sobra de arredondamento atribuindo a diferença à maior reserva do lote.
> - Testes cobrindo: o fechamento exato da soma, o rateio proporcional correto, e o caso de reserva com valor zero.
> - Uma aba nova em app_repasses.py mostrando o rateio por proprietário.
>
> Siga as convenções do CLAUDE.md: determinismo, português, dataclasses para configuração, teste para toda lógica nova. Rode a suíte inteira ao final.

---

## Prompt 3 — Preparar para o cliente (só se o projeto for fechado)

> Fechei o projeto com o cliente. Preciso adaptar a ferramenta aos arquivos reais dele.
>
> Regras que não mudam: nenhum dado real entra no repositório. Crie uma pasta `dados/cliente/` já no .gitignore para trabalho local, e mantenha o repositório público apenas com dados sintéticos.
>
> Me ajude a: criar um leitor que aceite o formato de exportação dele, mapear as colunas para o esquema interno, e gerar o relatório final. Vamos por partes — primeiro me mostre o plano antes de escrever código.

---

## Comandos úteis

```bash
pip install -r requirements.txt      # dependências
pytest -q                            # 19 testes
streamlit run app_repasses.py        # demo do caso Airbnb
streamlit run app.py                 # demo da conciliação geral
python main.py --demo                # CLI + relatório Excel
python setup_projeto.py              # organiza arquivos soltos
```

## Deploy no Streamlit

- Repositório precisa ser **público**
- `requirements.txt` na raiz
- Main file path: `app_repasses.py` (demo prioritária, é a que o cliente vai ver)
- Segundo app do mesmo repositório: `app.py`
- Primeiro build leva de 2 a 5 minutos
- Apps gratuitos hibernam após dias sem acesso e levam ~30s para acordar — abra o link no dia em que enviar a proposta

## Regras que valem para qualquer etapa

1. Nenhum dado real de cliente ou empregador no repositório
2. Não ajustar teste para fazer passar — se o gabarito quebrou, o motor regrediu
3. Repositório público contém só dados sintéticos
4. Antes de push, rodar a suíte completa
