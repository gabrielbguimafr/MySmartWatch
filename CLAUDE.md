# smartData

## Orquestrador (modelos abertos)

Para delegar subtarefas bem delimitadas (gerar rascunhos de código, funções isoladas,
testes, revisões, análises), use o orquestrador em `C:\Users\gabri\Desktop\orquestrador`.
Ele envia cada subtarefa em paralelo para:

- `qwen` → OpenRouter, modelo definido em `MODELO_QWEN` (hoje um Nemotron, de propósito)
- `deepseek` → API da DeepSeek, modelo `MODELO_DEEPSEEK` — **indisponível no momento**
  (chave rejeitada com 401); use só `qwen` até o usuário avisar que corrigiu a chave.

### Como usar

1. Escreva as subtarefas em `.orquestrador/tarefas.json` (dentro do smartData):
   ```json
   [
     {"modelo": "qwen", "instrucao": "Escreva a função X ...", "arquivos": ["src/modulo.py"]},
     {"modelo": "deepseek", "instrucao": "Revise ..."}
   ]
   ```
   `arquivos` é opcional; caminhos relativos ao smartData; o conteúdo vai junto da instrução.
2. Rode a partir do smartData:
   ```
   python C:/Users/gabri/Desktop/orquestrador/main.py .orquestrador/tarefas.json .orquestrador/resultados
   ```
3. Leia as respostas em `.orquestrador/resultados/<data-hora>/NN_modelo.md`, revise,
   corrija e só então integre ao projeto. As respostas são rascunhos: nunca copie sem revisar.

### Regras

- Instruções autocontidas: os modelos não veem o projeto, só a instrução e os `arquivos`.
- Não envie segredos (`.env`, chaves, dados pessoais) em `arquivos`.
- Decisões de arquitetura e integração ficam com o Claude Code; o orquestrador é para trabalho paralelizável.
