/**
 * Portuguese (Brazil) for the **interface only**.
 *
 * The rule, and it has no exceptions: nothing that came out of the database is
 * in this file. No space names, no NER display names, no venue codes, no page
 * labels, no aliases, no audit entries, no file names. Those are the study's
 * data; they read identically in both languages because they *are* the same
 * thing, and a drawing that says "Observer Office 2" must be found by searching
 * "Observer Office 2" whatever language the buttons are in.
 *
 * Terms of art are also left alone on purpose. NER, TER, TEAP, VDB, IDF, COW,
 * MDF and the event's own vocabulary are what the project speaks in the room and
 * in every document that leaves it. Translating "NER register" to "registro de
 * NERs" is fine — the noun around it is interface. Translating "NER" itself
 * would be inventing a word nobody uses.
 *
 * Sample text inside placeholders ("Venue - VVV", "VVV", "TEAP v1") is
 * deliberately absent: it is example *data*, and it should look the same to
 * everyone.
 *
 * A key missing from this table renders as its English. That is the intended
 * failure mode — see the note in i18n.ts.
 */

import { DISCLAIMER } from "./notation";

export const PT: Record<string, string> = {
  // --- shell, navigation, top bar -----------------------------------------
  "NER Spatial Coverage Analyzer": "NER Spatial Coverage Analyzer",
  "TER / NER placement and coverage study": "Estudo de posicionamento e cobertura de TER / NER",
  "Projects": "Projetos",
  "Import": "Importação",
  "Scale": "Escala",
  "Drawing viewer": "Visualizador do desenho",
  "NERs": "NERs",
  "Marker review": "Revisão de marcadores",
  "NER register": "Registro de NERs",
  "On the drawing": "No desenho",
  "what the VDB says": "o que o VDB diz",
  "Register": "Registro",
  "what you decided": "o que você decidiu",
  "TEAP × drawing": "TEAP × desenho",
  "TEAP aliases": "Apelidos do TEAP",
  "Worklist — largest demand first": "Fila de trabalho — maior demanda primeiro",
  "row(s)": "linha(s)",
  "with no room chosen yet": "sem sala escolhida ainda",
  "ports still awaiting a decision": "portas ainda aguardando decisão",
  "The list is not restricted by name similarity: pick whichever room on the sheet is the right one, however differently it is named. If the space does not exist on this drawing at all, reject it.":
    "A lista não é restrita por semelhança de nome: escolha a sala certa na folha, por mais diferente que seja o nome. Se o espaço não existe neste desenho, rejeite-o.",
  "Remember": "Lembrar",
  "Served by": "Atendido por",
  "nearest:": "mais próxima:",
  "— nothing reaches it —": "— nada alcança —",
  "chosen by you": "escolhida por você",
  "space(s) assigned by you.": "espaço(s) atribuído(s) por você.",
  "Why should this room serve this space? Recorded in the audit log.":
    "Por que esta sala deve atender este espaço? Fica registrado no log de auditoria.",
  "Released — the nearest compatible room will serve it again. Re-run the analysis.":
    "Liberado — a sala compatível mais próxima volta a atender. Rode a análise de novo.",
  "Assigned. Re-run the analysis to see the effect — the distance and the capacity are still checked.":
    "Atribuído. Rode a análise de novo para ver o efeito — a distância e a capacidade continuam sendo verificadas.",
  "Each space goes to the nearest compatible room. Choose another one where you know better — a room that is full, or one that must not mix critical and non-critical services. Your choice survives every re-run, and the distance, the limit and the capacity go on being checked and reported exactly as they are.":
    "Cada espaço vai para a sala compatível mais próxima. Escolha outra onde você sabe mais — uma sala lotada, ou uma que não pode misturar serviços críticos e não críticos. Sua escolha sobrevive a toda reexecução, e a distância, o limite e a capacidade continuam sendo verificados e reportados exatamente como são.",
  "Port capacity is recorded on the Register tab, not here: this tab is what the drawing says, and how many ports a room has is something a person knows. It cannot be derived from which spaces the room serves — that gives the demand, not the supply. Capacity left blank is reported as “capacity unknown” and can never produce a removal recommendation, only a spatial-redundancy candidate.":
    "A capacidade de portas é registrada na aba Registro, não aqui: esta aba é o que o desenho diz, e quantas portas uma sala tem é algo que uma pessoa sabe. Não dá para derivar de quais espaços a sala atende — isso dá a demanda, não a oferta. Capacidade em branco é reportada como “capacidade desconhecida” e nunca gera recomendação de remoção, apenas candidata por redundância espacial.",
  "This screen could not be drawn": "Esta tela não pôde ser desenhada",
  "The fault is in the screen, not in your data — nothing was changed. Switching to another step or reloading will bring the application back.":
    "A falha é na tela, não nos seus dados — nada foi alterado. Mudar de passo ou recarregar traz o aplicativo de volta.",
  "Try this screen again": "Tentar esta tela de novo",
  "Reload the application": "Recarregar o aplicativo",
  "Technical detail": "Detalhe técnico",
  "Non-critical": "Não crítica",
  "Not stated on the drawing": "Não informado no desenho",
  "confirmed by you": "confirmado por você",
  "read from the drawing": "lido do desenho",
  "on the drawing": "no desenho",
  "removal proposed": "remoção proposta",
  "Propose removal": "Propor remoção",
  "Undo removal": "Desfazer remoção",
  "Accept this NER": "Aceitar esta NER",
  "Discard this NER": "Descartar esta NER",
  "Why should this room be removed? This becomes a change request for the drawing team.":
    "Por que esta sala deve ser removida? Isso vira um pedido de mudança para a equipe de desenho.",
  "suggested here — not drawn in the VDB": "sugerida aqui — não desenhada no VDB",
  "confirmed": "confirmado",
  "rejected": "rejeitado",
  "Noted. The rule will be written once you choose the room.":
    "Anotado. A regra será gravada assim que você escolher a sala.",
  "your choice — saved, and kept when the matching re-runs":
    "sua escolha — gravada, e mantida quando o matching rodar de novo",
  "you said this space is not on this drawing":
    "você disse que este espaço não está neste desenho",
  "Rule removed. It no longer applies to other venues.":
    "Regra removida. Ela não vale mais para outros venues.",
  "earlier decision(s) kept": "decisão(ões) anterior(es) preservada(s)",
  "decision(s) released — the room is no longer on the drawing":
    "decisão(ões) liberada(s) — a sala não está mais no desenho",
  "Re-running never clears a room you chose, confirmed or rejected. Those are stored on the TEAP line itself, not on this list.":
    "Rodar de novo nunca apaga uma sala que você escolheu, confirmou ou rejeitou. Isso fica gravado na própria linha do TEAP, não nesta lista.",
  "Write this as a rule that applies to every venue":
    "Gravar como regra válida para todos os venues",
  "Apply this pairing to every venue on this installation":
    "Aplicar este pareamento a todos os venues desta instalação",
  "remembered for every venue": "memorizado para todos os venues",
  // NER proposals read from a VDB comments tracker
  "Propose NERs from a VDB comments tracker":
    "Propor NERs a partir de um tracker de comentários do VDB",
  "For a drawing set with no NER on it. Reads the comment column you write against each VDB cycle, takes the room, the criticality and the sheet from your own sentence, and lists what it would create before anything is written.":
    "Para um conjunto de desenhos sem nenhuma NER. Lê a coluna de comentários que você escreve a cada ciclo de VDB, tira a sala, a criticidade e a folha da sua própria frase, e lista o que criaria antes de gravar qualquer coisa.",
  "Choose tracker…": "Escolher tracker…",
  "reading…": "lendo…",
  "rows with text": "linhas com texto",
  "proposal(s) read": "proposta(s) lida(s)",
  "proposals read": "propostas lidas",
  "placed": "posicionadas",
  "placed on the drawing": "posicionadas no desenho",
  "without a position": "sem posição",
  "critical": "críticas",
  "Tracker code": "Código no tracker",
  "Room named": "Sala citada",
  "Where it lands": "Onde fica",
  "Drawing sheet": "Folha",
  "The sentence it came from": "A frase de onde veio",
  "no position — it will be listed, not drawn":
    "sem posição — será listada, não desenhada",
  "serves": "atende",
  "A note about the venue, not about one room":
    "Uma nota sobre o venue, não sobre uma sala",
  // the proposed-NER layer in the drawing viewer
  "Rooms in the register that are not drawn on the sheet — proposals and suggestions":
    "Salas do registro que não estão desenhadas na folha — propostas e sugestões",
  "proposed": "proposta",
  "Proposed NERs": "NERs propostas",
  "proposed — not drawn on the sheet": "proposta — não desenhada na folha",
  "accepted — not drawn on the sheet": "aceita — não desenhada na folha",
  "accepted — not on the sheet": "aceita — fora da folha",
  "NER — accepted, not yet on the sheet": "NER — aceita, ainda não na folha",
  "Locked. Unlock it on the register to move it.":
    "Travada. Destrave no registro para poder mover.",
  "Drag it to move it. The move is recorded, and the row stops claiming to sit where the tracker or the solver put it.":
    "Arraste para mover. O movimento fica registrado, e a linha deixa de dizer que está onde o tracker ou o otimizador colocou.",
  "Sits inside": "Fica dentro de",
  "Accept or discard it on the NER register — this screen shows it, it does not decide it.":
    "Aceite ou descarte no registro de NERs — esta tela mostra, não decide.",
  "proposed NER(s) have no position yet — the space they name is not on this drawing set. They are listed on the NER register.":
    "NER(s) proposta(s) ainda sem posição — o espaço que elas citam não está neste conjunto de desenhos. Estão listadas no registro de NERs.",
  "Add these to the register as proposals":
    "Adicionar ao registro como propostas",
  "Discard": "Descartar",
  "They arrive as suggestions: not approved positions, and out of the As-Is analysis until you confirm them.":
    "Elas entram como sugestões: não são posições aprovadas, e ficam fora da análise As-Is até você confirmar.",
  "added": "adicionada(s)",
  "updated": "atualizada(s)",
  "left alone (already decided)": "mantida(s) intactas (já decididas)",
  "rooms available on this drawing.": "salas disponíveis neste desenho.",
  "Choosing one here is saved immediately and stays saved: re-running the matching never clears it. Remember is a separate, optional step — it copies the pairing to your other venues, and nothing else on this screen writes one.":
    "Escolher aqui grava na hora e continua gravado: rodar o matching de novo nunca apaga. Lembrar é um passo separado e opcional — copia o pareamento para os seus outros projetos, e nada mais nesta tela cria uma regra.",
  "Rules remembered across venues": "Regras memorizadas entre venues",
  "Curated pairings that outrank every automatic method and re-apply at every matching run. Click to open.":
    "Pareamentos curados que têm precedência sobre todo método automático e voltam a valer em cada rodada de matching. Clique para abrir.",
  "No rules yet. Tick Remember on a row above to create one.":
    "Nenhuma regra ainda. Marque Lembrar em uma linha acima para criar uma.",
  "Demand per space": "Demanda por ambiente",
  "Coverage analysis": "Análise de cobertura",
  "As-Is vs Proposed": "Atual vs Proposto",
  "Exceptions": "Exceções",
  "Reports": "Relatórios",
  "Account & security": "Conta e segurança",
  "Accounts & security": "Contas e segurança",
  "Administration": "Administração",
  "Your account": "Sua conta",
  "Your account, password and — for administrators — the other accounts":
    "Sua conta, sua senha e — para administradores — as outras contas",
  "Interface language. Project data, names and exports are never translated.":
    "Idioma da interface. Dados do projeto, nomes e exportações nunca são traduzidos.",
  "Sign out": "Sair",
  "No project selected": "Nenhum projeto selecionado",
  "venue": "venue",
  "Scale confirmed": "Escala confirmada",
  "page(s) awaiting scale": "página(s) aguardando escala",
  "limits": "limites",
  "slack": "folga",
  "scale": "escala",
  "not set": "não definida",
  "page": "página",
  "change your password": "troque sua senha",
  // A computed key, so the disclaimer can never drift out of sync with the
  // constant the screens actually render.
  [DISCLAIMER]:
    "Esta ferramenta apoia o processo de projeto. Não substitui aprovação de engenharia, " +
    "levantamento em campo, validação de rota de cabos ou inspeção física.",

  // --- projects ------------------------------------------------------------
  "New project": "Novo projeto",
  "Project name": "Nome do projeto",
  "Venue code (optional)": "Código do venue (opcional)",
  "Create": "Criar",
  "Open": "Abrir",
  "Name": "Nome",
  "Venue": "Venue",
  "Owner": "Dono",
  "Visible to": "Visível para",
  "Drawings": "Desenhos",
  "TEAP files": "Arquivos TEAP",
  "Scenarios": "Cenários",
  "only me": "somente eu",
  "accounts on this machine": "contas nesta máquina",
  "shared with you · read only": "compartilhado com você · somente leitura",
  "Shared means readable by the other accounts on this machine. Nothing is published anywhere.":
    "Compartilhado significa legível pelas outras contas desta máquina. Nada é publicado em lugar nenhum.",
  "No projects yet.": "Nenhum projeto ainda.",
  "No projects.": "Nenhum projeto.",
  "Select a project first.": "Selecione um projeto primeiro.",
  "Project created. Import the drawings and the TEAP next.":
    "Projeto criado. Importe os desenhos e o TEAP em seguida.",
  "Delete": "Excluir",

  // --- import --------------------------------------------------------------
  "1 · Drawings (PDF)": "1 · Desenhos (PDF)",
  "2 · TEAP (XLSX / XLSM / CSV)": "2 · TEAP (XLSX / XLSM / CSV)",
  "3 · Project rules": "3 · Regras do projeto",
  "File": "Arquivo",
  "Pages": "Páginas",
  "Spaces": "Ambientes",
  "Markers": "Marcadores",
  "OCR needed": "Precisa de OCR",
  "No drawing yet.": "Nenhum desenho ainda.",
  "Import a drawing first.": "Importe um desenho primeiro.",
  "Import a TEAP first.": "Importe um TEAP primeiro.",
  "Sheet and header row": "Aba e linha de cabeçalho",
  "Sheet": "Aba",
  "Header row": "Linha de cabeçalho",
  "Reading the venue column…": "Lendo a coluna de venue…",
  "Column mapping": "Mapeamento de colunas",
  "— none selected —": "— nenhum selecionado —",
  "— not mapped —": "— não mapeado —",
  "— none —": "— nenhum —",
  "— not stated —": "— não informado —",
  "Save this mapping as a reusable template (optional)":
    "Salvar este mapeamento como modelo reutilizável (opcional)",
  "General limit (m)": "Limite geral (m)",
  "Photographer limit (m)": "Limite de fotógrafo (m)",
  "Routing slack factor (≥ 1)": "Fator de folga de roteamento (≥ 1)",
  "Near-limit threshold (0–1)": "Limiar de proximidade do limite (0–1)",
  "Fallback grid spacing (m)": "Espaçamento da malha de fallback (m)",
  "Display units": "Unidades de exibição",
  "Naming convention": "Convenção de nomes",
  "Save rules": "Salvar regras",
  "Project rules saved.": "Regras do projeto salvas.",
  "Import a dictionary from another venue": "Importar um dicionário de outro venue",

  // --- scale and viewer ----------------------------------------------------
  "Scale per page": "Escala por página",
  "Set (ratio or text)": "Definir (proporção ou texto)",
  "Set": "Definir",
  "Lock": "Travar",
  "Fit": "Ajustar",
  "Radii": "Raios",
  "LEGEND": "LEGENDA",
  "Inspector": "Inspetor",
  "Label for the new element": "Rótulo do novo elemento",
  "Label for this zone": "Rótulo desta zona",
  "Vertical length in metres": "Comprimento vertical em metros",
  "Page number this shaft connects to": "Número da página a que este shaft se conecta",
  "Nothing to confirm on this page yet.": "Nada a confirmar nesta página ainda.",
  "scale not confirmed": "escala não confirmada",

  // --- the notation (legend, kinds, statuses) ------------------------------
  "NER — critical": "NER — crítica",
  "NER — non critical": "NER — não crítica",
  "NER — proposed": "NER — proposta",
  "NER — redundancy candidate": "NER — candidata a redundância",
  "IDF / MDF": "IDF / MDF",
  "COW / temporary": "COW / temporária",
  "Shaft / riser": "Shaft / prumada",
  "Unclassified": "Não classificado",
  "Area served": "Área atendida",
  "Area near the limit": "Área próxima do limite",
  "Area out of coverage": "Área fora de cobertura",
  "Served": "Atendido",
  "Near the limit": "Próximo do limite",
  "Out of limit": "Fora do limite",
  "Insufficient capacity": "Capacidade insuficiente",
  "Match not confirmed": "Correspondência não confirmada",
  "Scale not confirmed": "Escala não confirmada",
  "Route not validated": "Rota não validada",
  "Not analysable": "Não analisável",
  "No NER reaches it": "Nenhuma NER alcança",
  "No room on the drawing — NER chosen by you": "Sem sala no desenho — NER escolhida por você",

  // --- marker review and the NER register ----------------------------------
  "Detected TER / NER — review and capacity": "TER / NER detectados — revisão e capacidade",
  "NER Register and Review": "Registro e revisão de NERs",
  "NERs in the register": "NERs no registro",
  "Review queue": "Fila de revisão",
  "Possible duplicates": "Possíveis duplicatas",
  "Frozen snapshots": "Snapshots congelados",
  "Freeze the register": "Congelar o registro",
  "Code": "Código",
  "internal identifier — never changes": "identificador interno — nunca muda",
  "Label": "Rótulo",
  "Name — what you will cite later": "Nome — o que você vai citar depois",
  "Kind": "Tipo",
  "Level": "Nível",
  "Status": "Situação",
  "Classification": "Classificação",
  "Criticality": "Criticidade",
  "Critical": "Crítica",
  "Criticality unconfirmed": "Criticidade não confirmada",
  "criticality unconfirmed": "criticidade não confirmada",
  "Keep": "Manter",
  "Reject": "Rejeitar",
  "Remove": "Remover",
  "Reposition": "Reposicionar",
  "Keep / reject undecided": "Manter / rejeitar em aberto",
  "Undecided": "Em aberto",
  "Decision": "Decisão",
  "Occurrences": "Ocorrências",
  "Occurrences in documents": "Ocorrências nos documentos",
  "Documental occurrences": "Ocorrências documentais",
  "Doc": "Doc",
  "Identity and history": "Identidade e histórico",
  "Consolidation history": "Histórico de consolidação",
  "Evidence": "Evidências",
  "Evidence they are the same room": "Evidências de que são o mesmo ambiente",
  "Differences found": "Diferenças encontradas",
  "Comparing the register…": "Comparando o registro…",
  "Confidence": "Confiança",
  "Conf.": "Conf.",
  "Score": "Pontuação",
  "Outstanding validations": "Validações pendentes",
  "nothing outstanding": "nada pendente",
  "Why it is here": "Por que está aqui",
  "Why this NER was suggested": "Por que esta NER foi sugerida",
  "Filter by name, code, level or alias": "Filtrar por nome, código, nível ou apelido",
  "Only rows still awaiting a decision": "Somente linhas ainda aguardando decisão",
  "all statuses": "todas as situações",
  "Identified": "Identificada",
  "Suggested": "Sugerida",
  "In review": "Em revisão",
  "Confirmed": "Confirmada",
  "Confirmed with constraints": "Confirmada com restrições",
  "Reposition proposed": "Reposicionamento proposto",
  "Rejected": "Rejeitada",
  "Consolidated": "Consolidada",
  "Change request": "Solicitação de mudança",
  "Design freeze": "Congelamento do projeto",
  "Baseline": "Linha de base",
  "Reference": "Referência",
  "Issued to": "Emitido para",
  "VNI team": "Equipe VNI",
  "Refresh from a new analysis": "Atualizar a partir de uma nova análise",
  "or leave it for later — nothing changes": "ou deixe para depois — nada muda",
  "what makes you sure": "o que te dá certeza",

  // --- matching and aliases ------------------------------------------------
  "TEAP × drawing matching": "Correspondência TEAP × desenho",
  "Run matching": "Executar correspondência",
  "Match on": "Corresponder por",
  "TEAP row": "Linha do TEAP",
  "TEAP code": "Código do TEAP",
  "TEAP name": "Nome do TEAP",
  "TEAP value": "Valor do TEAP",
  "Drawing space": "Ambiente do desenho",
  "Drawing value (code or exact room name)": "Valor no desenho (código ou nome exato do ambiente)",
  "Method": "Método",
  "Confirm": "Confirmar",
  "Record an alias": "Registrar um apelido",
  "Create alias": "Criar apelido",
  "No aliases yet.": "Nenhum apelido ainda.",
  "Alias saved. Re-run the matching step to apply it.":
    "Apelido salvo. Execute a correspondência novamente para aplicá-lo.",
  "Nothing pending. Run the matching step if you have not yet.":
    "Nada pendente. Execute a correspondência se ainda não executou.",
  "space code": "código do ambiente",
  "space name": "nome do ambiente",
  "Scope": "Escopo",
  "Qualifier": "Qualificador",
  "Rule": "Regra",

  // --- demand, coverage, scenarios ----------------------------------------
  "Network port demand per space": "Demanda de portas de rede por ambiente",
  "Demand type": "Tipo de demanda",
  "Total demand": "Demanda total",
  "Total ports": "Portas totais",
  "Ports": "Portas",
  "Ports assigned": "Portas atribuídas",
  "Qty": "Qtd.",
  "Product": "Produto",
  "Room": "Ambiente",
  "Rooms": "Ambientes",
  "Rooms in the proposal": "Ambientes na proposta",
  "Space": "Ambiente",
  "Space → NER": "Ambiente → NER",
  "Coverage analysis (As-Is)": "Análise de cobertura (Atual)",
  "Coverage overlay updated.": "Sobreposição de cobertura atualizada.",
  "As-Is coverage computed.": "Cobertura atual calculada.",
  "Run analysis": "Executar análise",
  "Distance": "Distância",
  "Limit": "Limite",
  "Margin": "Margem",
  "Served spaces": "Ambientes atendidos",
  "Longest serving distance": "Maior distância de atendimento",
  "NER load and capacity": "Carga e capacidade das NERs",
  "Utilisation": "Utilização",
  "Capacity": "Capacidade",
  "Used": "Usado",
  "Reserved": "Reservado",
  "Summary": "Resumo",
  "Metric": "Métrica",
  "Detail": "Detalhe",
  "Detected": "Detectado",
  "Origin": "Origem",
  "Source": "Fonte",
  "Type": "Tipo",
  "Note": "Nota",
  "Notes": "Notas",
  "Warnings": "Avisos",
  "Blockers": "Impedimentos",
  "Assumptions": "Premissas",
  "Explanation": "Explicação",
  "Expected result": "Resultado esperado",
  "Worklist — unresolved spaces, largest demand first":
    "Lista de trabalho — ambientes não resolvidos, maior demanda primeiro",
  "Run “Coverage” to see this space's assignment.":
    "Execute “Cobertura” para ver a atribuição deste ambiente.",
  "As-Is": "Atual",
  "Proposed": "Proposto",
  "Delta": "Variação",
  "Compare As-Is vs Proposed": "Comparar Atual vs Proposto",
  "Optimise": "Otimizar",
  "Optimised proposal": "Proposta otimizada",
  "Max new NERs (blank = unlimited)": "Máximo de novas NERs (vazio = sem limite)",
  "Spatial redundancy candidates": "Candidatas a redundância espacial",
  "Areas it would serve": "Áreas que atenderia",
  "Out of coverage before": "Fora de cobertura antes",
  "still uncovered": "ainda sem cobertura",
  "not covered": "sem cobertura",
  "not analysed": "não analisado",
  "within limits": "dentro dos limites",
  "worst distance (m)": "pior distância (m)",
  "rooms opened": "ambientes abertos",
  "general (90 m)": "geral (90 m)",
  "photographer (70 m)": "fotógrafo (70 m)",
  "photographer areas": "áreas de fotógrafo",
  "unknown — never read as zero": "desconhecido — nunca leia como zero",
  "The model is too large to solve — see the notes below.":
    "O modelo é grande demais para resolver — veja as notas abaixo.",
  "runs the placement solver and adds its new sites to the register as suggestions":
    "executa o solver de posicionamento e adiciona os novos pontos ao registro como sugestões",
  "Coverage exceptions": "Exceções de cobertura",
  "Reason / exception": "Motivo / exceção",
  "Applied": "Aplicado",
  "Coverage": "Cobertura",
  "TOTAL": "TOTAL",
  "TEAP": "TEAP",

  // --- reports and audit ---------------------------------------------------
  "Exports": "Exportações",
  "Analysis workbook (XLSX)": "Planilha de análise (XLSX)",
  "Coverage CSV": "CSV de cobertura",
  "with legend": "com legenda",
  "The legend box is 320 pt wide and on a dense sheet it sits over the drawing. Turned off, the limits, the scale and the disclaimer stay as three small lines along the foot of the page.":
    "A caixa de legenda tem 320 pt de largura e, numa folha carregada, cai por cima do desenho. Desligada, os limites, a escala e o aviso legal ficam em três linhas pequenas no pé da página.",
  "Marked-up PDF": "PDF marcado",
  "Positions outside the page": "Posições fora da página",
  "The marked-up PDF marks every page of the book, so on a large venue it takes a minute or two. It runs in the background — the progress bar names the page it is on, and the rest of the app stays usable.":
    "O PDF marcado marca todas as páginas do caderno, então num venue grande leva um ou dois minutos. Ele roda em segundo plano — a barra de progresso diz em que página está, e o resto do app continua utilizável.",
  "drawn from the saved snapshot": "desenhado a partir do snapshot salvo",
  "no snapshot saved — the live analysis will be used":
    "nenhum snapshot salvo — será usada a análise atual",
  "item(s) sit outside their page — re-import the drawing":
    "item(ns) estão fora da página — reimporte o desenho",
  "These were marked where they are stored, not moved. A drawing imported before the page-rotation correction keeps the old coordinates — re-import it and they will fall into place.":
    "Foram marcados onde estão gravados, sem serem movidos. Um desenho importado antes da correção de rotação de página mantém as coordenadas antigas — reimporte-o e tudo cai no lugar.",
  "Page size": "Tamanho da página",
  "Export JSON": "Exportar JSON",
  "Audit log": "Log de auditoria",
  "Actor": "Autor",
  "Action": "Ação",
  "Actions": "Ações",
  "Entity": "Entidade",
  "When": "Quando",
  "By": "Por",
  "Payload": "Conteúdo",
  "Justification": "Justificativa",
  "Justification (recorded in the audit log)": "Justificativa (registrada no log de auditoria)",
  "Reason": "Motivo",
  "Reason — recorded in the audit log": "Motivo — registrado no log de auditoria",
  "Reason / justification — recorded in the audit log":
    "Motivo / justificativa — registrado no log de auditoria",
  "Cancel": "Cancelar",
  "Dismiss": "Descartar",
  "Add": "Adicionar",
  "Link": "Vincular",
  "Project": "Projeto",
  "Created": "Criado",
  "None.": "Nenhum.",

  // --- accounts and security ----------------------------------------------
  "Sign in": "Entrar",
  "Create the first account": "Criar a primeira conta",
  "Username": "Usuário",
  "Password": "Senha",
  "Password again": "Repita a senha",
  "Current password": "Senha atual",
  "New password": "Nova senha",
  "Display name": "Nome de exibição",
  "Initial password": "Senha inicial",
  "Accounts": "Contas",
  "Add an account": "Adicionar uma conta",
  "Admin": "Admin",
  "Active": "Ativo",
  "Sessions": "Sessões",
  "Last signed in": "Último acesso",
  "Reset password": "Redefinir senha",
  "The two passwords do not match.": "As duas senhas não conferem.",
  "Where this data lives": "Onde estes dados ficam",

  // --- server messages -----------------------------------------------------
  // Keyed by the exact English the API returns. `tests/test_i18n.py` fails if
  // any of these stops matching the backend source, so an edit on the server
  // side cannot silently strand a translation here.
  "sign in to continue": "entre para continuar",
  "this needs an administrator account": "isso exige uma conta de administrador",
  "project not found": "projeto não encontrado",
  // 2.4.1 — the two reasons the matching step cannot run, told apart
  "import a TEAP before running the matching step":
    "importe um TEAP antes de rodar o cruzamento",
  "ingest at least one drawing before running the matching step":
    "importe pelo menos um desenho antes de rodar o cruzamento",
  "the drawing was ingested but no space was recognised on it — no space code and no room-name label was found, so there is nothing to match the TEAP against; ingest the drawing again on this version, or check that the sheets carry room labels":
    "o desenho foi importado, mas nenhum espaço foi reconhecido nele — não há código de espaço nem rótulo com nome de sala, então não há com o que cruzar o TEAP; importe o desenho de novo nesta versão ou confira se as folhas trazem rótulos de sala",
  "the current password is not right": "a senha atual não está correta",
  "user not found": "usuário não encontrado",
  "you cannot disable your own account": "você não pode desativar a própria conta",
  "you cannot remove your own administrator rights":
    "você não pode remover os próprios direitos de administrador",
  "you cannot delete your own account": "você não pode excluir a própria conta",
  // --- marker review, register, criticality --------------------------------
  "Show the inspector": "Mostrar o inspetor",
  "Hide the inspector": "Ocultar o inspetor",
  "Click to show only this kind": "Clique para ver só este tipo",
  "Filter by label": "Filtrar por rótulo",
  "all pages": "todas as páginas",
  "Clear filters": "Limpar filtros",
  "of": "de",
  "Rename — recorded in the audit log": "Renomear — registrado no log de auditoria",
  "Page in the drawing": "Página no desenho",
  "no position": "sem posição",
  "also on": "também em",
  "Proposed on page": "Proposta na página",
  "Based on TEAP spaces matched to the drawing":
    "Baseada em ambientes do TEAP com correspondência no desenho",

  // --- the memory guard ----------------------------------------------------
  "Not enough memory on this computer right now — nothing was changed. See below.":
    "Memória insuficiente neste computador agora — nada foi alterado. Veja abaixo.",
  "not enough memory on this computer to run the optimiser right now":
    "memória insuficiente neste computador para rodar o otimizador agora",
  "this project is shared with you for reading. Ask its owner to make the change, or take your own copy.":
    "este projeto foi compartilhado com você somente para leitura. Peça ao dono para fazer a alteração, ou faça a sua própria cópia.",
  "type the username exactly to confirm — this deletes their projects too":
    "digite o nome de usuário exatamente para confirmar — isso exclui também os projetos dele",
  "username or password is not right": "usuário ou senha incorretos",
  "this account is disabled — ask an administrator":
    "esta conta está desativada — procure um administrador",
  "this installation already has accounts — ask an administrator to create yours":
    "esta instalação já tem contas — peça a um administrador para criar a sua",
  "a username is 2–40 characters: lower case letters, digits, dot, dash or underscore, starting with a letter or digit":
    "um nome de usuário tem de 2 a 40 caracteres: letras minúsculas, dígitos, ponto, hífen ou sublinhado, começando por letra ou dígito",
  "the password cannot start or end with a space":
    "a senha não pode começar nem terminar com espaço",
  "deleting a user and their projects requires a reason":
    "excluir um usuário e seus projetos exige um motivo",
  "this is the last active administrator — promote someone else first, or the installation becomes unmanageable":
    "este é o último administrador ativo — promova outra pessoa antes, senão a instalação fica ingerenciável",
  "a project with that name already exists": "já existe um projeto com esse nome",
  "no drawing uploaded": "nenhum desenho enviado",
  "drawing not found": "desenho não encontrado",
  "the stored file is missing": "o arquivo armazenado está faltando",
  "page not found": "página não encontrada",
  "supply a denominator, a scale text, or two calibration points":
    "informe um denominador, um texto de escala, ou dois pontos de calibração",
  "element not found": "elemento não encontrado",
  "element is locked": "o elemento está travado",
  "element is locked: unlock it before moving it":
    "o elemento está travado: destrave antes de movê-lo",
  "space not found": "ambiente não encontrado",
  "drawing space not found": "ambiente do desenho não encontrado",
  "TEAP file not found": "arquivo TEAP não encontrado",
  "match not found": "correspondência não encontrada",
  "alias not found": "apelido não encontrado",
  "scenario not found": "cenário não encontrado",
  "report not found": "relatório não encontrado",
  "occurrence not found in this project": "ocorrência não encontrada neste projeto",
  "a zone needs at least three points": "uma zona precisa de pelo menos três pontos",
  "no drawing to mark up": "nenhum desenho para marcar",

  // --- the September simplification pass -----------------------------------
  "Register NERs": "NERs do registro",
  "Rooms in the register that carry no marker on this sheet":
    "Salas do registro que não têm marcação nesta folha",
  "NER(s) in the register have no position on this drawing set. Place them with the +NER tools.":
    "NER(s) do registro sem posição neste conjunto de desenhos. Posicione-as com as ferramentas +NER.",
  "not on the sheet": "não está na folha",
  "in the register — not drawn on the sheet":
    "no registro — não desenhada na folha",
  "Drag it to move it. The move is recorded.":
    "Arraste para mover. A movimentação fica registrada.",
  "Only rows whose criticality has not been confirmed":
    "Apenas as linhas cuja criticidade ainda não foi confirmada",
  "rooms chosen by you": "salas escolhidas por você",
  "— not analysed yet —": "— ainda não analisado —",
  "The serving NER is read from the last coverage run —":
    "A NER que atende vem da última análise de cobertura —",
  "Change it here and re-run the analysis to see the effect.":
    "Altere aqui e rode a análise de novo para ver o efeito.",
  "No coverage analysis has been run yet, so no serving NER can be shown. Run it on the Coverage analysis step.":
    "Nenhuma análise de cobertura foi rodada ainda, então não há NER atendente a mostrar. Rode na etapa Coverage analysis.",
  "The list is not restricted by name similarity: pick whichever room on the sheet is the right one, however differently it is named. A line with no room chosen stays on the list and is reported as an exception.":
    "A lista não é limitada por semelhança de nome: escolha a sala certa na folha, por mais diferente que seja o nome. Uma linha sem sala escolhida permanece na lista e é reportada como exceção.",
  "The workbook opens on a sheet shaped like the TEAP itself — every space, every service, every port — with the NER serving it, whether that NER is critical, and how far away it is. A second sheet lists the NERs and their ports. The scales, the matching evidence and the exceptions follow.":
    "A planilha abre numa aba com o formato do próprio TEAP — cada espaço, cada serviço, cada porta — com a NER que atende, se essa NER é crítica e a que distância está. Uma segunda aba lista as NERs e suas portas. Em seguida vêm as escalas, as evidências do cruzamento e as exceções.",
  "Every change to this project, with the person who made it and the reason they gave.":
    "Toda alteração neste projeto, com quem a fez e a justificativa que deu.",
  "Load the audit log": "Carregar o log de auditoria",
  "Port capacity is recorded on the Register tab, not here: this tab is what the drawing says, and how many ports a room has is something a person knows. It cannot be derived from which spaces the room serves — that gives the demand, not the supply. Capacity left blank is reported as “capacity unknown”.":
    "A capacidade de portas é registrada na aba Register, não aqui: esta aba é o que o desenho diz, e quantas portas uma sala tem é algo que uma pessoa sabe. Não dá para deduzir a partir dos espaços que a sala atende — isso dá a demanda, não a oferta. Capacidade em branco é reportada como “capacidade desconhecida”.",

  // --- 3 Sep 2026 screen pass ------------------------------------------------
  // Scale
  "Confirm all pages": "Confirmar todas as páginas",
  "Confirms the detected (or typed) scale on every page that has one": "Confirma a escala detectada (ou digitada) em todas as páginas que têm uma",
  "Confirm the scale on": "Confirmar a escala em",
  "page(s) at once?": "página(s) de uma vez?",
  "Each page keeps the value shown in its Applied column. Pages with no scale are left alone.": "Cada página mantém o valor mostrado na coluna Applied. Páginas sem escala ficam como estão.",
  "page(s) confirmed": "página(s) confirmada(s)",
  "page(s) have no scale to confirm": "página(s) sem escala para confirmar",
  "page(s) with no scale — type one in the row": "página(s) sem escala — digite uma na linha",
  "Detected scales are proposals only. Definitive coverage results stay blocked until each page is confirmed. Type a ratio or a scale text in the row to override what was detected.":
    "As escalas detectadas são apenas propostas. Os resultados definitivos de cobertura ficam bloqueados até cada página ser confirmada. Digite uma razão ou um texto de escala na linha para substituir o que foi detectado.",
  "Sheet / level": "Folha / nível",
  // Drawing viewer
  "DIVA node": "DIVA node",
  "Drawn on the plan only — never serves a space": "Só desenhado na planta — nunca atende um espaço",
  "Click a marker or a space. Drag an unlocked marker to move it; the change is written to the audit log. The +NER tools place a room the study is about; +TER, +IDF, +COW and +DIVA draw what is in the building and never serve a space.":
    "Clique num marcador ou num espaço. Arraste um marcador destravado para movê-lo; a alteração vai para o log de auditoria. As ferramentas +NER colocam uma sala que faz parte do estudo; +TER, +IDF, +COW e +DIVA desenham o que existe no prédio e nunca atendem um espaço.",
  "drawn by you": "desenhada por você",
  "from the drawing": "herdada do desenho",
  "from the tracker": "do tracker",
  "suggested": "sugerida",
  "Rename — the marker on the sheet follows; recorded in the audit log": "Renomear — o marcador na folha acompanha; registrado no log de auditoria",
  "awaiting confirmation": "aguardando confirmação",
  "Unconfirm": "Desconfirmar",
  "Unlock": "Destravar",
  "used": "usadas",
  "reserved": "reservadas",
  "unknown": "desconhecida",
  "deleted from the drawing": "excluído do desenho",
  "moved on the drawing": "movido no desenho",
  // NERs — one screen
  "One row per NER, whether it came from the drawing or you drew it — the Origin column says which. One name: renaming a room here relabels its marker on the sheet, and the label the drawing printed is kept in its history. Choosing the criticality confirms it. A TER, an IDF, a COW or a DIVA node is not a row here: it is drawn, moved and renamed in the Drawing viewer and takes part in nothing else.":
    "Uma linha por NER, herdada do desenho ou desenhada por você — a coluna Origin diz qual. Um nome só: renomear a sala aqui renomeia o marcador na folha, e o rótulo impresso no desenho fica guardado no histórico. Escolher a criticidade já é confirmá-la. TER, IDF, COW e DIVA node não são linhas aqui: são desenhados, movidos e renomeados no Drawing viewer e não participam de mais nada.",
  "not confirmed": "não confirmadas",
  "criticality not stated": "criticidade não informada",
  "capacity unknown": "capacidade desconhecida",
  "Confirm all": "Confirmar todas",
  "Confirms the criticality and every marker of every NER that is not confirmed yet": "Confirma a criticidade e todos os marcadores de cada NER ainda não confirmada",
  "Unconfirm all": "Desconfirmar todas",
  "Lock all": "Travar todas",
  "Locks every NER against being moved on the drawing": "Trava todas as NERs contra movimento no desenho",
  "Unlock all": "Destravar todas",
  "only rows not confirmed yet": "só as linhas ainda não confirmadas",
  "Lock every NER against being moved?": "Travar todas as NERs contra movimento?",
  "Unlock every NER?": "Destravar todas as NERs?",
  "Confirm every NER — its criticality and every marker of it on the drawing?": "Confirmar todas as NERs — a criticidade e todos os marcadores de cada uma no desenho?",
  "Take the confirmation back on every NER?": "Retirar a confirmação de todas as NERs?",
  "NER(s)": "NER(s)",
  "skipped": "ignorada(s)",
  "Also on the drawing, managed in the Drawing viewer": "Também no desenho, gerenciados no Drawing viewer",
  "p.": "p.",
  "Removed": "Removidas",
  "Removed NERs": "NERs removidas",
  "Nothing is deleted: a removed NER keeps its row, its markers and the reason, and can be restored.": "Nada é apagado: uma NER removida mantém a linha, os marcadores e o motivo, e pode ser restaurada.",
  "Restore": "Restaurar",
  "restored": "restaurada",
  "Capacity (ports)": "Capacidade (portas)",
  "Details": "Detalhes",
  "Close": "Fechar",
  "Evidence per marker, outstanding validations, history and notes": "Evidências por marcador, validações pendentes, histórico e notas",
  "No NER yet. Import a drawing, or place one by hand in the Drawing viewer with the +NER tools.": "Nenhuma NER ainda. Importe um desenho ou coloque uma à mão no Drawing viewer com as ferramentas +NER.",
  "No row matches this filter.": "Nenhuma linha corresponde a este filtro.",
  "Locked — unlock it to rename": "Travada — destrave para renomear",
  "Locked — unlock it to remove": "Travada — destrave para remover",
  "Locked against being moved on the drawing": "Travada contra movimento no desenho",
  "Confirmed: the criticality is right and every marker of this room on the drawing is real": "Confirmada: a criticidade está certa e todos os marcadores desta sala no desenho são reais",
  "Remove from the drawing and the analysis (restorable)": "Remover do desenho e da análise (restaurável)",
  "Why — recorded in the audit log": "Por quê — registrado no log de auditoria",
  "not in the design": "não está no projeto",
  "removed on the NERs screen": "removida na tela NERs",
  "removed — it leaves the drawing and the analysis; Restore brings it back": "removida — sai do desenho e da análise; Restore traz de volta",
  "chosen on the NERs screen": "escolhida na tela NERs",
  "was": "era",
  "Internal id": "Id interno",
  "code": "código",
  "neither changes when the name does.": "nenhum dos dois muda quando o nome muda.",
  "Label printed on the drawing": "Rótulo impresso no desenho",
  "Also known as": "Também conhecida como",
  "by": "por",
  "Criticality read from": "Criticidade lida de",
  "Markers on the drawing": "Marcadores no desenho",
  "yes": "sim",
  "no": "não",
  "This marker is a different room: give it a row of its own": "Este marcador é outra sala: dê a ele uma linha própria",
  "Separate": "Separar",
  "marker separated into its own NER": "marcador separado numa NER própria",
  "No marker on the sheet — the room is drawn from its register position.": "Sem marcador na folha — a sala é desenhada a partir da posição do registro.",
  "No pair in the list looks like the same room twice. A pair you have already answered — merged, or declared different — stops appearing here.": "Nenhum par da lista parece ser a mesma sala duas vezes. Um par já respondido — consolidado ou declarado diferente — deixa de aparecer aqui.",
  "strong evidence": "evidência forte",
  "needs judgement": "precisa de julgamento",
  "none": "nenhuma",
  "Consolidating moves": "Consolidar move",
  "marker(s)": "marcador(es)",
  "and reassigns": "e reatribui",
  "served area(s)": "área(s) atendida(s)",
  "and": "e",
  "Same NER — consolidate": "Mesma NER — consolidar",
  "Different NERs": "NERs diferentes",
  "consolidated — reversible from the history": "consolidada — reversível pelo histórico",
  "recorded as different rooms": "registradas como salas diferentes",
  "Every link the tool made on its own is here with its evidence, alongside every decision a person made. A merge can be undone; the list goes back exactly as it was.": "Todo vínculo que a ferramenta criou sozinha está aqui com a evidência, junto de cada decisão tomada por uma pessoa. Uma consolidação pode ser desfeita; a lista volta exatamente ao que era.",
  "undone": "desfeita",
  "Undo": "Desfazer",
  "consolidation undone": "consolidação desfeita",
  "Nothing consolidated yet.": "Nada consolidado ainda.",
  // TEAP × drawing
  "Order: exact space code → base code → exact name → normalised name → synonyms → text similarity → building/level context. Low-confidence and ambiguous results are never confirmed silently — each one is yours to check against the sheet.":
    "Ordem: código exato do espaço → código-base → nome exato → nome normalizado → sinônimos → similaridade de texto → contexto de prédio/nível. Resultados ambíguos ou de baixa confiança nunca são confirmados em silêncio — cada um é seu para conferir na folha.",
  "Re-running never clears a room you chose or confirmed. Those are stored on the TEAP line itself, not on this list.": "Rodar de novo nunca apaga uma sala que você escolheu ou confirmou. Isso fica gravado na própria linha do TEAP, não nesta lista.",
  "Matched": "Cruzados",
  "TEAP spaces": "espaços do TEAP",
  "matched": "cruzados",
  "still need review": "ainda precisam de revisão",
  "no room found": "sem sala encontrada",
  "Choose the room first": "Escolha a sala primeiro",
  "Choosing one here is saved immediately and stays saved: re-running the matching never clears it. Every pairing belongs to this project alone — nothing here is carried to another venue.": "Escolher uma aqui é salvo na hora e continua salvo: rodar o cruzamento de novo nunca apaga. Cada pareamento pertence só a este projeto — nada daqui é levado para outra venue.",
  // Demand per space (with the analysis)
  "Demand per space and the NER that serves it": "Demanda por espaço e a NER que o atende",
  "Last run": "Última rodada",
  "No analysis yet — the rows show demand only.": "Nenhuma análise ainda — as linhas mostram só a demanda.",
  "spaces": "espaços",
  "ports": "portas",
  "rooms named by the TEAP": "salas nomeadas pelo TEAP",
  "The room comes from the TEAP when its sheet names one, from you when you choose one on the row, and otherwise from the rule: the nearest NER within the limit that still has free ports — the next one if the nearest is full, and the nearest anyway, flagged, if every room within reach is full. Distance, limit and capacity are checked and reported whichever way the room was chosen.":
    "A sala vem do TEAP quando a planilha nomeia uma, de você quando escolhe uma na linha, e senão da regra: a NER mais próxima dentro do limite que ainda tem portas livres — a seguinte se a mais próxima estiver cheia, e a mais próxima mesmo assim, sinalizada, se todas ao alcance estiverem cheias. Distância, limite e capacidade são verificados e reportados seja qual for a forma de escolha.",
  "Coverage computed — the serving NER, the distance and the status on every row are from this run.": "Cobertura calculada — a NER atendente, a distância e o status de cada linha são desta rodada.",
  "Released — the rule chooses the room again. Re-run the analysis.": "Liberado — a regra volta a escolher a sala. Rode a análise de novo.",
  "general": "geral",
  "photographer": "fotógrafos",
  "named in the TEAP — no doubt": "nomeada no TEAP — sem dúvida",
  "the TEAP names": "o TEAP nomeia",
  "no NER with that name on the NERs screen": "nenhuma NER com esse nome na tela NERs",
  "— none within": "— nenhuma a menos de",
  "— not matched to the drawing —": "— sem correspondência no desenho —",
  "match not confirmed": "cruzamento não confirmado",
  "route not validated": "rota não validada",
  "nearest": "mais próxima",
  "at": "a",
  "straight line": "linha reta",
  "Straight-line screening distance; validate against the cable route": "Distância preliminar em linha reta; valide contra a rota do cabeamento",
  "No space has this status.": "Nenhum espaço tem este status.",
  "Ports assigned to each NER by the last run against its capacity. Click to open.": "Portas atribuídas a cada NER na última rodada contra a capacidade dela. Clique para abrir.",
  "over capacity": "acima da capacidade",
  "FA": "FA",
  "Page": "Página",
  // 10 Sep 2026 — from → to, the "other level" box, readable notes, the
  // drawing number beside the page, the lines switch on Reports
  "Matched to": "Associado a",
  "The room on the drawing this TEAP line was tied to. An arrow means it was tied to a room with a different code — decided on TEAP × drawing.":
    "A sala do desenho à qual esta linha do TEAP foi associada. Uma seta indica que foi associada a uma sala com outro código — decidido em TEAP × drawing.",
  "— not matched —": "— sem correspondência —",
  "tied by hand": "associada à mão",
  "matched, confirmed": "cruzada, confirmada",
  "matched, not confirmed": "cruzada, não confirmada",
  "same room": "mesma sala",
  "tied to another room": "associados a outra sala",
  "TEAP spaces tied to a drawing room with a different code — see the Matched to column": "Espaços do TEAP associados a uma sala do desenho com outro código — veja a coluna Matched to",
  "other level": "outro nível",
  "is on": "está na",
  "this space is on": "este espaço está na",
  "unticked: the room is not counted": "desmarcado: a sala não é contada",
  "The room you chose is on another page. Ticked, its ports count against that room and the distance is reported as not measured until a shaft, riser or vertical route is registered. Unticked, the room is not counted.":
    "A sala que você escolheu está em outra página. Marcado, as portas contam na capacidade dessa sala e a distância aparece como não medida até que um shaft, riser ou rota vertical seja cadastrado. Desmarcado, a sala não é contada.",
  "recorded as served from another level ('other level' ticked): its ports count against that room, and the distance is reported as not measured until a shaft or riser is registered. Re-run the analysis.":
    "registrado como atendido de outro nível ('other level' marcado): as portas contam na capacidade dessa sala, e a distância aparece como não medida até que um shaft ou riser seja cadastrado. Rode a análise de novo.",
  "other level — not measured": "outro nível — não medida",
  "Served from another page/level with no vertical route registered: the distance was not measured.": "Atendido de outra página/nível sem rota vertical cadastrada: a distância não foi medida.",
  "via vertical route": "por rota vertical",
  "Other level — not measured": "Outro nível — não medida",
  "Open every row's notes in full, or fold them back": "Abrir as notas de todas as linhas por inteiro, ou recolhê-las",
  "open all": "abrir todas",
  "fold all": "recolher todas",
  "fold": "recolher",
  "read": "ler",
  "Click to read every note": "Clique para ler todas as notas",
  "with NER → space lines": "com linhas NER → espaço",
  "The dotted lines from each space to the NER that serves it, with the distance written on them. Turned off, the markers, the area colours and the legend stay exactly as they are.":
    "As linhas pontilhadas de cada espaço até a NER que o atende, com a distância escrita nelas. Desligadas, os marcadores, as cores das áreas e a legenda ficam exatamente como estão.",
  "Page number - drawing number from the title block": "Número da página - número do desenho lido do carimbo",
  // the TEAP × drawing tiles, relabelled 10 Sep 2026 so they add up on screen
  "matched, not yet confirmed": "cruzados, ainda não confirmados",
  "not on this drawing (rejected by you)": "não está neste desenho (rejeitado por você)",
  // the version, shown on the sign-in screen and under the title
  "version": "versão",
  "interface": "interface",
  "server": "servidor",
  "the application was updated — press Ctrl+Shift+R to load the current interface":
    "o aplicativo foi atualizado — pressione Ctrl+Shift+R para carregar a interface atual",
  // 2.2.0 — the TEAP rules, zero-port spaces, the same space on several pages, wireless points
  // 2.5.0 — indoor / outdoor access points, and the TEAP space each one stands in for
  "Wi-Fi point placed for":
    "ponto Wi-Fi posicionado para",
  "Check it in the Inspector; click again to place another, choose select to stop.":
    "Confira no Inspector; clique de novo para criar outro, escolha select para parar.",
  "Wi-Fi point placed — no matched room within the limit on this sheet, so it belongs to no TEAP space and counts no port. Tie it to a space in the Inspector if it belongs to one.":
    "ponto Wi-Fi posicionado — nenhuma sala casada dentro do limite nesta folha, então não pertence a nenhum espaço TEAP e não conta porta. Amarre-o a um espaço no Inspector se ele pertencer a um.",
  "An indoor access point: one port on the nearest NER within the limit, standing in for the wireless port the TEAP requests for the space":
    "Um access point interno: uma porta na NER mais próxima dentro do limite, no lugar da porta de wireless que o TEAP pede para o espaço",
  "An outdoor access point: one port on the nearest NER within the limit, standing in for the wireless port the TEAP requests for the space":
    "Um access point externo: uma porta na NER mais próxima dentro do limite, no lugar da porta de wireless que o TEAP pede para o espaço",
  "Stands in for (TEAP space)": "Substitui (espaço do TEAP)",
  "The TEAP space this Wi-Fi point belongs to. Its wireless port is that space's DWISA line, counted on the space whatever is drawn; the point adds no port.":
    "O espaço TEAP a que este ponto Wi-Fi pertence. A porta wireless é a linha DWISA desse espaço, contada no espaço seja o que for desenhado; o ponto não acrescenta porta.",
  "— none (not in the TEAP, no port) —":
    "— nenhum (fora do TEAP, sem porta) —",
  "On this page": "Nesta página",
  "Other pages": "Outras páginas",
  "TEAP wireless": "wireless no TEAP",
  "tied by you": "vinculado por você",
  "nearest matched room on this sheet — proposed; change it if the point serves another space":
    "sala cruzada mais próxima nesta folha — proposta; troque se o ponto atende outro espaço",
  "cleared by you — not in the TEAP, no port":
    "limpo por você — fora do TEAP, sem porta",
  "no matched room within the limit on this sheet — not in the TEAP, no port":
    "nenhuma sala casada dentro do limite nesta folha — fora do TEAP, sem porta",
  "Wireless point — indoor AP": "Wireless point — AP interno",
  "Wireless point — outdoor AP": "Wireless point — AP externo",
  "indoor": "interno",
  "outdoor": "externo",
  "— none: not in the TEAP, no port —":
    "— nenhum: fora do TEAP, sem porta —",
  "Indoor APs": "APs internos",
  "Outdoor APs": "APs externos",
  "Click a marker or a space. Drag an unlocked marker to move it; the change is written to the audit log. The +NER tools place a room the study is about; +TER, +IDF, +COW and +DIVA draw what is in the building and never serve a space. +AP in and +AP out place a wireless point (an indoor or outdoor access point): one port on the nearest NER within the limit, standing in for the wireless port the TEAP requests for the space.":
    "Clique em um marcador ou em um espaço. Arraste um marcador destravado para movê-lo; a alteração fica no log de auditoria. As ferramentas +NER criam uma sala que é objeto do estudo; +TER, +IDF, +COW e +DIVA desenham o que existe no prédio e nunca atendem um espaço. +AP in e +AP out criam um wireless point (access point interno ou externo): uma porta na NER mais próxima dentro do limite, no lugar da porta de wireless que o TEAP pede para o espaço.",
  "A Wi-Fi point takes no port and is not an access point count: the DWISA line of its TEAP space is the port. It is measured to the NER of its space, or the nearest within the limit.":
    "Um ponto Wi-Fi não ocupa porta e não é contagem de access points: a linha DWISA do seu espaço TEAP é a porta. Ele é medido até a NER do seu espaço, ou a mais próxima dentro do limite.",
  "Serving NER":
    "NER que atende",
  "none within the limit":
    "nenhuma dentro do limite",
  "Not analysed yet — press Coverage on this screen to measure it.":
    "Ainda não analisado — pressione Coverage nesta tela para medir.",
  "The TEAP rules. The check runs from the TEAP to the drawing, never the other way round: a room on the drawing that no TEAP line asks for is not listed and not a finding. A TEAP line the matcher could not place is yours to tie by hand to any room on the drawing.":
    "O TEAP manda. A checagem vai do TEAP para o desenho, nunca o contrário: uma sala do desenho que nenhuma linha do TEAP pede não é listada nem é um achado. Uma linha do TEAP que o matcher não conseguiu localizar é sua para ligar à mão a qualquer sala do desenho.",
  "show TEAP spaces with no ports":
    "mostrar espaços do TEAP sem portas",
  "Rooms on the drawing not tied to any TEAP line":
    "Salas do desenho sem ligação com nenhuma linha do TEAP",
  "Rooms already tied to a TEAP line":
    "Salas já ligadas a uma linha do TEAP",
  "no ports requested in the TEAP — not part of the study":
    "nenhuma porta pedida no TEAP — fora do estudo",
  "Recorded as the same space. Re-run the analysis: the distance is measured from the page the NER is on.":
    "Registrado como o mesmo espaço. Rode a análise de novo: a distância é medida na página onde a NER está.",
  "Recorded as a different space — that page is not used for this row. Re-run the analysis.":
    "Registrado como outro espaço — aquela página não é usada nesta linha. Rode a análise de novo.",
  "The TEAP says whether an area is served. A TEAP space that requests no port is not matched by hand, not analysed and not listed here.":
    "É o TEAP que diz se uma área é atendida. Um espaço do TEAP que não pede nenhuma porta não é cruzado à mão, não é analisado e não aparece aqui.",
  "Wireless points drawn in the Drawing viewer — one port each on the NER that reaches them":
    "Wireless points desenhados no Drawing viewer — uma porta cada na NER que os alcança",
  "wireless points":
    "wireless points",
  "The same code or name is on another page and nobody has said whether it is the same space — see the row":
    "O mesmo código ou nome está em outra página e ninguém disse ainda se é o mesmo espaço — veja a linha",
  "same space on another page? — to confirm":
    "mesmo espaço em outra página? — a confirmar",
  "same code, same level":
    "mesmo código, mesmo nível",
  "same space, confirmed by you":
    "mesmo espaço, confirmado por você",
  "not the same space":
    "não é o mesmo espaço",
  "same name, no code":
    "mesmo nome, sem código",
  "same code":
    "mesmo código",
  "is":
    "está a",
  "from it there":
    "dele naquela página",
  "Same space":
    "Mesmo espaço",
  "Not the same":
    "Não é o mesmo",
  "not the same space (your answer)":
    "não é o mesmo espaço (resposta sua)",
  "undo":
    "desfazer",
  "The same space is labelled on more than one page; the distance was measured on the page the serving NER is on.":
    "O mesmo espaço aparece em mais de uma página; a distância foi medida na página onde está a NER que o atende.",
  "measured on":
    "medido na",
  "Wireless points":
    "Wireless points",
  "Placed from the TEAP on the Scale screen (one per space with wireless), or drawn by hand in the Drawing viewer (+Wi-Fi). A Wi-Fi point marks a space that has wireless; it is not an access point count and takes no port. The wireless port is the DWISA line of its TEAP space, counted on that space's row and on the NER that serves the space. Each point is measured to the NER of its space (or the nearest within the general limit) so the 90 m rule is checked where the point is drawn; a point with no NER within reach is listed as an exception.":
    "Posicionados a partir do TEAP na tela Scale (um por espaço com wireless), ou desenhados à mão no Drawing viewer (+Wi-Fi). Um ponto Wi-Fi marca um espaço que tem wireless; não é contagem de access points e não ocupa porta. A porta wireless é a linha DWISA do seu espaço TEAP, contada na linha desse espaço e na NER que atende o espaço. Cada ponto é medido até a NER do seu espaço (ou a mais próxima dentro do limite geral), para conferir a regra dos 90 m onde o ponto está desenhado; um ponto sem NER ao alcance vai para as exceções.",
  "Wireless point":
    "Wireless point",
  "NER":
    "NER",
  "TEAP locations with no space on the drawings":
    "Localizações do TEAP sem espaço nos desenhos",
  "Only TEAP spaces that request ports are listed. The check runs from the TEAP to the drawing: a room on the drawing that no TEAP line asks for is not an exception.":
    "Só aparecem os espaços do TEAP que pedem portas. A checagem vai do TEAP para o desenho: uma sala do desenho que nenhuma linha do TEAP pede não é exceção.",
  "TEAP spaces with no ports — left off the list":
    "espaços do TEAP sem portas — fora da lista",
  "Computing coverage…":
    "Calculando a cobertura…",
  "same level by the drawing number":
    "mesmo nível pelo número do desenho",
  "level not read":
    "nível não lido",
  // 2.3.0 — erase anything drawn, from the viewer
  "Eraser: click a marker, a wireless point, a named area, a route segment or a shaft to delete it. Stays on until you choose select.":
    "Borracha: clique num marcador, num wireless point, num trecho de rota ou num shaft para apagá-lo. Fica ligada até você escolher select.",
  "this route segment":
    "este trecho de rota",
  "the shaft between pages":
    "o shaft entre as páginas",
  "locked — unlock it before deleting it":
    "travado — destrave antes de apagar",
  "Re-run the analysis to see the effect.":
    "Rode a análise de novo para ver o efeito.",
  "Route segment":
    "Trecho de rota",
  "pages":
    "páginas",
  "Distances are measured along traced routes instead of the straight line. Deleting this segment changes them at the next analysis.":
    "As distâncias são medidas pelas rotas traçadas em vez da linha reta. Apagar este trecho muda essas distâncias na próxima análise.",
  "A shaft is what lets a NER on one page be measured to a space on another. Deleting it puts those spaces back to 'other level — not measured'.":
    "O shaft é o que permite medir de uma NER numa página até um espaço em outra. Apagá-lo devolve esses espaços a 'other level — not measured'.",
  "Or press Delete on the keyboard.":
    "Ou pressione Delete no teclado.",
  "A point placed by mistake is deleted here or in the Drawing viewer.":
    "Um ponto criado por engano se apaga aqui ou no Drawing viewer.",

  // 2.6.0 — the tiles are the filter on TEAP × drawing, and Undo takes a decision back
  "exact code, confirmed by the matcher":
    "código exato, confirmado pelo matcher",
  "no room found — choose one by hand":
    "sem sala encontrada — escolha uma à mão",
  "with no room found — choose one by hand":
    "sem sala encontrada — escolha uma à mão",
  "your decisions — kept on every re-run":
    "suas decisões — mantidas em toda rodada",
  "Click again to show every row":
    "Clique de novo para mostrar todas as linhas",
  "Click to show only these rows":
    "Clique para mostrar só estas linhas",
  "The tiles add up two ways: matched + no room found (+ not on this drawing) = TEAP spaces; matched = confirmed by you + exact code, confirmed by the matcher + matched, not yet confirmed. Your decisions cut across those. TEAP spaces with no ports are outside the study and outside the sum.":
    "Os quadros fecham de dois jeitos: matched + no room found (+ not on this drawing) = TEAP spaces; matched = confirmed by you + exact code, confirmed by the matcher + matched, not yet confirmed. Suas decisões atravessam esses grupos. Os espaços do TEAP sem portas estão fora do estudo e fora da soma.",
  "Showing only":
    "Mostrando só",
  "show every row":
    "mostrar todas as linhas",
  "No row on this tile.":
    "Nenhuma linha neste quadro.",
  "back to the matcher's answer":
    "de volta à resposta do matcher",
  "Take back your decision on this row and show the matcher's answer again":
    "Desfaz a sua decisão nesta linha e mostra de novo a resposta do matcher",
  "Take back your decision on this row; run the matching to see the matcher's answer again":
    "Desfaz a sua decisão nesta linha; rode o cruzamento para ver de novo a resposta do matcher",
  "your decision was undone; run the matching to bring the matcher's answer back on this row":
    "sua decisão foi desfeita; rode o cruzamento para trazer de volta a resposta do matcher nesta linha",
  "Click a marker, a space or a named area. Drag an unlocked marker to move it; the change is written to the audit log. The +NER tools place a room the study is about; +TER, +IDF, +COW and +DIVA draw what is in the building and never serve a space. +AP in and +AP out place a wireless point (an indoor or outdoor access point): one port on the nearest NER within the limit, standing in for the wireless port the TEAP requests for the space. The illustrative tools (violet) are drawn and counted nowhere: *NER★ and *NER place a reference to a NER on a key plan, named after a NER of the register and drawn with its reach circles to this sheet's scale; *TER, *COW and *DIVA do the same for those rooms, without circles; +area draws a named area (BTOC, TER, a compound) — click each corner, double-click or Enter to close it. To take anything back: select it and press Delete (or the Delete button here), or arm the delete tool and click what should go.":
    "Clique em um marcador, em um espaço ou em uma área nomeada. Arraste um marcador destravado para movê-lo; a alteração fica no log de auditoria. As ferramentas +NER criam uma sala que é objeto do estudo; +TER, +IDF, +COW e +DIVA desenham o que existe no prédio e nunca atendem um espaço. +AP in e +AP out criam um wireless point (access point interno ou externo): uma porta na NER mais próxima dentro do limite, no lugar da porta de wireless que o TEAP pede para o espaço. As ferramentas ilustrativas (em violeta) são só desenho e não contam em nada: *NER★ e *NER criam uma referência a uma NER numa planta-chave, com o nome de uma NER do registro e os raios de alcance na escala desta folha; *TER, *COW e *DIVA fazem o mesmo para essas salas, sem raios; +area desenha uma área nomeada (BTOC, TER, um compound) — clique em cada canto, dê dois cliques ou Enter para fechar. Para desfazer qualquer coisa: selecione e pressione Delete (ou o botão Delete aqui), ou ligue a ferramenta delete e clique no que deve sair.",

  // 2.6.1 — the server down or restarting, seen from the browser
  "the server is not answering — it is restarted automatically within about two minutes, and this page reconnects by itself":
    "o servidor não está respondendo — ele é reiniciado automaticamente em cerca de dois minutos, e esta página reconecta sozinha",
  "server not answering — reconnecting":
    "servidor sem resposta — reconectando",
  "the server is back":
    "o servidor voltou",
  // 2.7.0 — the four piles on Demand per space, the unplaced rule, the NER
  // references on a key plan, the suggested names
  "Out of limit / over capacity": "Fora do limite / acima da capacidade",
  "Served — not measured": "Atendido — não medido",
  "Pending — needs a room or a NER": "Pendente — precisa de sala ou NER",
  "within the limit": "dentro do limite",
  "near the limit": "perto do limite",
  "out of limit": "fora do limite",
  "insufficient capacity": "capacidade insuficiente",
  "no NER reaches it": "nenhuma NER alcança",
  "no room on the drawing": "sem sala no desenho",
  "not analysed yet": "ainda não analisado",
  "no room on the drawing — NER chosen by you": "sem sala no desenho — NER escolhida por você",
  "all spaces": "todos os espaços",
  "all": "todos",
  "The four piles, and under each the precise reason from the last run":
    "Os quatro grupos e, em cada um, o motivo exato da última análise",
  "Click to show only these rows; click again for all":
    "Clique para mostrar só estas linhas; clique de novo para todas",
  "— no room on the drawing: choose the NER that serves it —":
    "— sem sala no desenho: escolha a NER que atende —",
  "no room on the drawing — counted on this NER, distance not measured":
    "sem sala no desenho — contado nesta NER, distância não medida",
  "This TEAP space is not on the drawing. The room you chose serves it: its ports count against that room and no distance is measured.":
    "Este espaço do TEAP não está no desenho. A sala que você escolheu o atende: as portas contam contra essa sala e nenhuma distância é medida.",
  "A TEAP space with no room on the drawing is pending until you tie it to a room on TEAP × drawing or choose its NER here: then its ports count against that NER and the distance is reported as not measured.":
    "Um espaço do TEAP sem sala no desenho fica pendente até você amarrá-lo a uma sala em TEAP × drawing ou escolher a NER aqui: aí as portas contam contra essa NER e a distância é informada como não medida.",
  "Reference (key plan) — drawn only, not counted": "Referência (planta-chave) — só desenho, não conta",
  "Named area — illustrative only": "Área nomeada — só ilustrativa",
  "TER reference (key plan)": "Referência de TER (planta-chave)",
  "COW reference (key plan)": "Referência de COW (planta-chave)",
  "DIVA node reference (key plan)": "Referência de DIVA node (planta-chave)",
  "NER reference — critical (key plan)": "Referência de NER — crítica (planta-chave)",
  "NER reference — non critical (key plan)": "Referência de NER — não crítica (planta-chave)",
  "A reference to a NER on a key plan: named after a NER of the register, drawn with its 90 m / 70 m circles to this sheet's scale, and counted nowhere — no register row, no TEAP link, no port":
    "Uma referência a uma NER numa planta-chave: com o nome de uma NER do registro, desenhada com os círculos de 90 m / 70 m na escala desta folha, sem contar em nada — sem linha no registro, sem vínculo com o TEAP, sem porta",
  "A reference on a key plan: it points at a NER drawn on another sheet. Drawn only, with its reach circles to this sheet's scale — no register row, no TEAP link, no port, nothing counted.":
    "Uma referência numa planta-chave: aponta para uma NER desenhada em outra folha. Só desenho, com os raios de alcance na escala desta folha — sem linha no registro, sem vínculo com o TEAP, sem porta, nada contado.",
  "Points at (NER of the register)": "Aponta para (NER do registro)",
  "— a name of its own (type it below) —": "— um nome próprio (digite abaixo) —",
  "— name it after: ask each time —": "— nome: perguntar a cada uma —",
  "The NER this reference is named after. Click the sheet to place it.":
    "A NER que dá nome a esta referência. Clique na folha para colocá-la.",
  "Name of the NER this reference points at": "Nome da NER para a qual esta referência aponta",
  "reference placed on this sheet — drawn only, with its reach circles; nothing is counted. Click again to place another, choose select to stop.":
    "referência colocada nesta folha — só desenho, com os raios de alcance; nada é contado. Clique de novo para colocar outra, escolha select para parar.",
  "Suggested name": "Nome sugerido",
  "From the naming convention and the spaces the room serves in the last run. Adopt it, edit the name, or leave it.":
    "Da convenção de nomes e dos espaços que a sala atende na última análise. Adote, edite o nome ou deixe como está.",
  "Adopt": "Adotar",
  "adopted": "adotado",
  "no number for": "sem número para",
  "add it to the convention": "acrescente à convenção",
  "no suggestion yet": "sem sugestão ainda",
  "The prefixes and the functional-area numbers the suggested names are built from":
    "Os prefixos e os números por área funcional que formam os nomes sugeridos",
  "A NER is named after the functional area it serves: the prefix says whether it is critical, the number says which area, and a second room of the same area gets \".1\". The area a room serves is read off the last coverage run — the area with the most ports among the spaces the room serves; a room that serves nothing yet is placed by the nearest matched room on its sheet, and that suggestion is marked weak. Words are matched whole against the TEAP space code, functional area and name (OVR matches OVR.001 and \"OVR Office\", not \"Overflow\"). A room whose area is not in the table is numbered in sequence after the named areas — critical rooms first, then by ports — as the ALA sheet does with NERc.08 and NERc.09; a number already adopted by any room is never handed out again.":
    "Uma NER recebe o nome da área funcional que atende: o prefixo diz se é crítica, o número diz a área, e uma segunda sala da mesma área recebe \".1\". A área que a sala atende é lida da última análise de cobertura — a área com mais portas entre os espaços que a sala atende; uma sala que ainda não atende nada é posicionada pela sala cruzada mais próxima na folha, e essa sugestão é marcada como fraca. As palavras são comparadas inteiras com o código, a área funcional e o nome do espaço do TEAP (OVR bate com OVR.001 e \"OVR Office\", não com \"Overflow\"). Uma sala cuja área não está na tabela é numerada em sequência depois das áreas nomeadas — as críticas primeiro, depois por portas — como a planilha ALA faz com NERc.08 e NERc.09; um número já adotado por qualquer sala nunca é entregue de novo.",
  "Sequence for the rest starts at": "Sequência das demais começa em",
  "The first number given to a room whose area is not in the table. 0 turns the sequence off: such rooms get no suggestion.":
    "O primeiro número dado a uma sala cuja área não está na tabela. 0 desliga a sequência: essas salas ficam sem sugestão.",
  "Critical prefix": "Prefixo crítica",
  "Non-critical prefix": "Prefixo não crítica",
  "Separator": "Separador",
  "TER prefix": "Prefixo TER",
  "e.g.": "ex.:",
  "Number": "Número",
  "Functional area": "Área funcional",
  "Words that identify it (comma-separated)": "Palavras que a identificam (separadas por vírgula)",
  "Add an area": "Adicionar área",
  "Save convention": "Salvar convenção",
  "Reset to default": "Voltar ao padrão",
  "Convention saved — the suggested names were recomputed.":
    "Convenção salva — os nomes sugeridos foram recalculados.",
  "Convention reset to the default (the ALA sheet).":
    "Convenção de volta ao padrão (a planilha ALA).",
  "Suggestions read from the run of": "Sugestões lidas da análise de",
  "No coverage run yet — suggestions fall back to the nearest room and are weak. Run the analysis on Demand per space.":
    "Ainda sem análise de cobertura — as sugestões usam a sala mais próxima e são fracas. Rode a análise em Demand per space.",
  "Loading the convention…": "Carregando a convenção…",

  // --- 2.8.0: named areas, TER/COW/DIVA references, the illustrative group, fibre runs
  "Illustrative tools: drawn on the sheet and in the marked-up PDF, counted nowhere":
    "Ferramentas ilustrativas: desenhadas na folha e no PDF marcado, não contam em nada",
  "A reference to a TER, a COW or a DIVA node on a key plan: named after the real one, drawn with a dashed ring, counted nowhere":
    "Uma referência a uma TER, um COW ou um DIVA node numa planta-chave: com o nome do real, desenhada com anel tracejado, não conta em nada",
  "A named area, to point something out (BTOC, TER, a compound): click each corner, double-click or press Enter to close it, then name it. Illustrative only — nothing is counted from it":
    "Uma área nomeada, para apontar algo (BTOC, TER, um compound): clique em cada canto, dê dois cliques ou Enter para fechar, depois dê o nome. Só ilustrativa — nada é contado a partir dela",
  "corner(s) — double-click or Enter to close, Esc to drop": "canto(s) — dois cliques ou Enter para fechar, Esc para descartar",
  "click the first corner of the area": "clique no primeiro canto da área",
  "An area needs at least three corners — keep clicking, then double-click or press Enter to close it.":
    "Uma área precisa de pelo menos três cantos — continue clicando e dê dois cliques ou Enter para fechar.",
  "Name of the area (for example BTOC, TER, broadcast compound)": "Nome da área (por exemplo BTOC, TER, broadcast compound)",
  "area drawn — illustrative only, nothing is counted from it. Click to start another, choose select to stop.":
    "área desenhada — só ilustrativa, nada é contado a partir dela. Clique para começar outra, escolha select para parar.",
  "the area": "a área",
  "Name of the room this reference points at": "Nome da sala que esta referência aponta",
  "A reference on a key plan: it points at a room drawn on another sheet. Drawn only — no register row, no TEAP link, nothing counted, no reach circles.":
    "Uma referência numa planta-chave: aponta para uma sala desenhada em outra folha. Só desenho — sem linha no registro, sem vínculo com o TEAP, nada contado, sem raios de alcance.",
  "Named area": "Área nomeada",
  "Illustrative only: drawn on the sheet and in the marked-up PDF to point something out. Nothing is measured or counted from it.":
    "Só ilustrativa: desenhada na folha e no PDF marcado para apontar algo. Nada é medido nem contado a partir dela.",
  "corners": "cantos",
  "ports assigned": "portas atribuídas",
  "utilisation": "utilização",
  "wireless point(s)": "wireless point(s)",
  "Fibre runs to the TER — per critical NER": "Fibras até a TER — por NER crítica",
  "Fibre runs to the TER — per non-critical NER": "Fibras até a TER — por NER não crítica",
  "Counted on the NERs and ports sheet and totalled on the Summary sheet. A count of runs, not a length.":
    "Contadas na aba NERs and ports e somadas na aba Summary. Uma contagem de lances, não um comprimento.",
  // --- 2.8.1: the strings the test pass found in English on the Portuguese screens
  "Account": "Conta",
  "Account created — they must change the password on first use.": "Conta criada — a pessoa precisa trocar a senha no primeiro uso.",
  "Account events": "Eventos de conta",
  "Load the account events": "Carregar os eventos de conta",
  "Sign-ins, accounts created, blocked, reset and deleted, with the reason given. These are not tied to a project, so they are not in a project's audit log.":
    "Logins, contas criadas, bloqueadas, com senha redefinida e excluídas, com o motivo informado. Não pertencem a um projeto, por isso não aparecem no registro de auditoria de um projeto.",
  "All": "Todas as",
  "Apply a saved mapping template": "Aplicar um modelo de mapeamento salvo",
  "— choose a template —": "— escolha um modelo —",
  "Template applied": "Modelo aplicado",
  "columns not in this sheet, left as they were": "colunas que não existem nesta aba, deixadas como estavam",
  "At least 10 characters. A phrase you can remember beats a short scramble — length is what resists guessing.":
    "Pelo menos 10 caracteres. Uma frase que você lembra vale mais que um embaralhado curto — é o comprimento que resiste à adivinhação.",
  "Cancelled": "Cancelado",
  "Failed": "Falhou",
  "Finished": "Concluído",
  "Working": "Trabalhando",
  "Change password": "Trocar senha",
  "Delete permanently": "Excluir permanentemente",
  "Type the username to confirm": "Digite o nome de usuário para confirmar",
  "Drawing imported": "Desenho importado",
  "TER/NER markers": "marcadores TER/NER",
  "page(s) need OCR": "página(s) precisam de OCR",
  "Every decision you record is written to the audit log under this name.": "Toda decisão que você registra vai para o registro de auditoria com este nome.",
  "Signed in as": "Conectado como",
  "administrator": "administrador",
  "Import TEAP": "Importar TEAP",
  "Importing all of them against one venue's drawings compares rooms in one venue with equipment rooms in another, and makes the placement model enormous. Pick the venue this project covers.":
    "Importar todos contra os desenhos de um venue compara salas de um venue com salas de equipamentos de outro, e torna o modelo enorme. Escolha o venue que este projeto cobre.",
  "This sheet is a master allocation plan": "Esta aba é um plano de alocação mestre",
  "venues": "venues",
  "rows": "linhas",
  "Will import": "Vai importar",
  "rows will be imported. Only do this if the project really does cover every venue.":
    "linhas serão importadas. Só faça isso se o projeto realmente cobre todos os venues.",
  "Venue filter": "Filtro de venue",
  "project venue": "venue do projeto",
  "import every venue": "importar todos os venues",
  "Reload venue list": "Recarregar a lista de venues",
  "No venue column is mapped, so the whole sheet will be imported.": "Nenhuma coluna de venue está mapeada, então a aba inteira será importada.",
  "Macros are never executed. Formulas are read as their cached values.": "Macros nunca são executadas. Fórmulas são lidas pelo valor em cache.",
  "Pick a venue, or tick “import every venue” to confirm you mean all of them.": "Escolha um venue, ou marque “importar todos os venues” para confirmar que quer todos.",
  "“space name” must be mapped — it is the key the drawing match is built on.": "“space name” precisa estar mapeado — é a chave em que a correspondência com o desenho se apoia.",
  "Workbook read": "Planilha lida",
  "sheet(s). Check the mapping, then load the venue list.": "aba(s). Confira o mapeamento e depois carregue a lista de venues.",
  "rows imported into": "linhas importadas em",
  "earlier decision(s) carried across": "decisão(ões) anterior(es) mantida(s)",
  "The 90 m rule in ANSI/TIA-568 is the permanent link — real cable length, not a straight line on a plan. A slack factor of 1.0 reports the raw geometry; raise it (1.25–1.40 is typical for a bowl) before treating any result as a design decision.":
    "Os 90 m da ANSI/TIA-568 são o permanent link — comprimento real de cabo, não uma linha reta na planta. Fator de folga 1.0 reporta a geometria crua; aumente (1.25–1.40 é típico de uma arena) antes de tratar qualquer resultado como decisão de projeto.",
  "metres": "metros",
  "feet": "pés",
  "both": "ambos",
  "you": "você",
  "and everything in it?": "e tudo o que há nele?",
  "only the owner can delete this project": "só o dono pode excluir este projeto",
  "Readable by the other accounts on this installation.": "Legível pelas outras contas desta instalação.",
  "Private again — only you and administrators.": "Privado de novo — só você e os administradores.",
  "New password for": "Nova senha para",
  "Password changed.": "Senha trocada.",
  "Password reset.": "Senha redefinida.",
  "deleted with": "excluído(a) com",
  "project(s)": "projeto(s)",
  "This installation has no accounts yet. The first one is an administrator and can create the others. Any projects already on this machine will be transferred to it.":
    "Esta instalação ainda não tem contas. A primeira é administradora e pode criar as outras. Projetos que já existam nesta máquina passam para ela.",
  "This password was set by an administrator. Change it now.": "Esta senha foi definida por um administrador. Troque agora.",
  "What this does not protect": "O que isto não protege",
  "Shaft registered between pages": "Shaft registrado entre as páginas",
  "reference placed on this sheet — drawn only, no reach circles; nothing is counted. Click again to place another, choose select to stop.":
    "referência colocada nesta folha — só desenho, sem raios de alcance; nada é contado. Clique de novo para colocar outra, escolha select para parar.",
  "Create account and sign in": "Criar conta e entrar",
  "— none (your choice) —":
    "— nenhuma (escolha sua) —",
  "you said this space is not on this drawing — kept when the matching re-runs; Undo takes it back":
    "você disse que este espaço não está neste desenho — mantido quando o cruzamento roda de novo; Undo desfaz",
  "✕ clear my choice — back to the TEAP's room":
    "✕ desfazer minha escolha — volta à sala do TEAP",
  "✕ clear my choice — back to the nearest NER rule":
    "✕ desfazer minha escolha — volta à regra da NER mais próxima",
  "✕ clear my choice — back to: no room on the drawing":
    "✕ desfazer minha escolha — volta a: sem sala no desenho",
  "other page":
    "outra página",
  "counted on this NER, distance not measured":
    "contado nesta NER, distância não medida",
  "The room you chose is on another page. Its ports count against that room and the distance is reported as not measured until a shaft, riser or vertical route is registered.":
    "A sala que você escolheu está em outra página. As portas contam nessa sala e a distância aparece como não medida até um shaft, riser ou rota vertical ser registrado.",
  "counted on that room from the other page: its ports count against it, and the distance is reported as not measured until a shaft or riser is registered. Re-run the analysis.":
    "contado nessa sala a partir da outra página: as portas contam nela, e a distância aparece como não medida até um shaft ou riser ser registrado. Rode a análise de novo.",
  "filtered by a counter below":
    "filtrado por um contador abaixo",
  "Venue type":
    "Tipo de venue",
  "Critical sequence":
    "Sequência crítica",
  "The first number for a critical room with no fixed number. 0: this venue type has none.":
    "O primeiro número para uma sala crítica sem número fixo. 0: este tipo de venue não tem.",
  "Non-critical from":
    "Não crítica a partir de",
  "At the TER within (m)":
    "Na TER, até (m)",
  "The critical NER nearest a TER marker on its sheet, within this distance, is NERc 01":
    "A NER crítica mais próxima de um marcador de TER na mesma folha, dentro desta distância, é a NERc 01",
  "the critical room nearest a TER marker":
    "a sala crítica mais próxima de um marcador de TER",
  "the NER of its TEAP space":
    "a NER do espaço do TEAP dele",
  "✕ clear my choice — back to its TEAP space's NER":
    "✕ desfazer minha escolha — volta à NER do espaço do TEAP",
  "as its TEAP space":
    "como o espaço do TEAP",
  "— nothing reaches it: choose the NER —":
    "— nada alcança: escolha a NER —",
  "assigned. Re-run the analysis to see the effect.":
    "atribuído. Rode a análise de novo para ver o efeito.",
  "released. Re-run the analysis to see the effect.":
    "liberado. Rode a análise de novo para ver o efeito.",
  // 2.12.0 — three tiles, Exceptions from the Demand rows, viewer search, NER name check
  "matched + no room found = TEAP spaces. Matched counts every line with a room, whether the matcher or you tied it; no room found counts every line without one, whether the matcher found none or you chose — none —. Each row says who decided.":
    "matched + no room found = TEAP spaces. Matched conta toda linha com uma sala, amarrada pelo matcher ou por você; no room found conta toda linha sem sala, porque o matcher não achou ou porque você escolheu — none —. Cada linha diz quem decidiu.",
  "matched line(s) still await your Confirm.":
    "linha(s) com sala ainda aguardam o seu Confirm.",
  "TEAP space(s) with no ports are outside the study and not counted.":
    "espaço(s) do TEAP sem portas ficam fora do estudo e não são contados.",
  "search code, name, room or NER":
    "buscar código, nome, sala ou NER",
  "Shows only the rows whose code, name, room on the drawing, FA or NER contain every word typed":
    "Mostra só as linhas cujo código, nome, sala no desenho, FA ou NER contêm todas as palavras digitadas",
  "near the limit (counted as served)":
    "perto do limite (contado como atendido)",
  "Served, within the limit but close to it. Counted in Served; click to see them":
    "Atendido, dentro do limite mas perto dele. Contado em Served; clique para ver",
  "No space answers this search with this filter.":
    "Nenhum espaço atende a esta busca com este filtro.",
  "wireless point":
    "ponto wireless",
  "Analysis re-run — the list is from this run.":
    "Análise refeita — a lista é desta rodada.",
  "Re-run the analysis":
    "Rodar a análise de novo",
  "The same rows as Demand per space, read from the last run and the choices made since. Every TEAP space that still needs you is here: with no room and no NER, out of the limit or over capacity, near the limit, or served from another level without a measured distance. Change the NER on the row, or open the row on Demand per space or on the drawing.":
    "As mesmas linhas da Demand per space, lidas da última rodada e das escolhas feitas depois dela. Todo espaço do TEAP que ainda precisa de você está aqui: sem sala e sem NER, fora do limite ou acima da capacidade, perto do limite, ou atendido de outro nível sem distância medida. Troque a NER na própria linha, ou abra a linha na Demand per space ou no desenho.",
  "Other NERs measured":
    "Outras NERs medidas",
  "✕ clear my choice — back to the rule":
    "✕ desfazer minha escolha — volta para a regra",
  "— no NER yet: choose one —":
    "— sem NER ainda: escolha uma —",
  "margin":
    "de folga",
  "not measured":
    "não medido",
  "no other NER on this page":
    "nenhuma outra NER nesta página",
  "Serve this space from this NER":
    "Atender este espaço a partir desta NER",
  "use":
    "usar",
  "Open this row on Demand per space":
    "Abrir esta linha na Demand per space",
  "Demand":
    "Demand",
  "Find it on the drawing":
    "Achar no desenho",
  "Drawing":
    "Desenho",
  "Nothing needs you here.":
    "Nada precisa de você aqui.",
  "Run the analysis to see what needs you.":
    "Rode a análise para ver o que precisa de você.",
  "Other NERs measured: the rooms the last run measured from this space, nearest first, the serving one left out. Only rooms on the same page (or joined by a registered shaft) are measured; a NER on another page is chosen in the Served by list and counted as not measured. A near-limit space whose next NER is out of the limit has no closer room today: that is a case for a new NER on the drawing.":
    "Outras NERs medidas: as salas que a última rodada mediu a partir deste espaço, da mais próxima para a mais distante, sem a que já atende. Só são medidas salas da mesma página (ou ligadas por um shaft cadastrado); uma NER de outra página é escolhida na lista Served by e contada como não medida. Um espaço perto do limite cuja próxima NER está fora do limite não tem sala mais próxima hoje: é caso de uma NER nova no desenho.",
  "all that need you":
    "tudo que precisa de você",
  "room on the drawing":
    "sala no desenho",
  "named area":
    "área nomeada",
  "Nothing on the drawing is named":
    "Nada no desenho se chama",
  "no page":
    "sem página",
  "A NER with this name already exists":
    "Já existe uma NER com este nome",
  "It is already drawn on this page.":
    "Ela já está desenhada nesta página.",
  "OK — it is the same NER, drawn on this page too (one room, counted once).":
    "OK — é a mesma NER, desenhada também nesta página (uma sala, contada uma vez).",
  "Cancel — it is a different room: choose another name.":
    "Cancelar — é outra sala: escolha outro nome.",
  "Another name for the new NER":
    "Outro nome para a NER nova",
  "drawn on this page as the same NER — one room in the register, counted once.":
    "desenhada nesta página como a mesma NER — uma sala no registro, contada uma vez.",
  "created on page":
    "criado na página",
  "search a name…":
    "buscar um nome…",
  "Find a room, a TEAP code tied to it, a NER or any marker, or a named area, on any page":
    "Acha uma sala, um código do TEAP amarrado a ela, uma NER ou qualquer marcador, ou uma área nomeada, em qualquer página",
  "nothing on the drawing has this name":
    "nada no desenho tem este nome",
  "more — type more of the name":
    "a mais — digite mais do nome",
  // 2.12.1
  "Rules not saved":
    "Regras não salvas",
  // 2.13.0 — key plans, NERs read off the room labels
  "Mark this page as a key plan? A key plan only illustrates: its rooms leave every TEAP × drawing crossing, a TEAP line tied to one of them is released, and the matching runs again.":
    "Marcar esta página como key plan? Uma key plan é só ilustrativa: as salas dela saem de todo cruzamento TEAP × drawing, a linha do TEAP amarrada a uma delas é solta e o matching roda de novo.",
  "Take this page off the key plans? Its rooms go back into the TEAP × drawing crossing and the matching runs again.":
    "Tirar esta página das key plans? As salas dela voltam para o cruzamento TEAP × drawing e o matching roda de novo.",
  "Page marked as a key plan.":
    "Página marcada como key plan.",
  "Page taken off the key plans.":
    "Página tirada das key plans.",
  "TEAP tie(s) to a room on this page released.":
    "amarração(ões) do TEAP com sala desta página solta(s).",
  "Matching run again.":
    "Matching rodado de novo.",
  "Still counted on this page — delete them or replace them with *NER references:":
    "Ainda contam nesta página — apague ou troque por referências *NER:",
  "A key plan only illustrates: its rooms are not drawn or listed and take part in no TEAP × drawing crossing, and no NER is created from it. Read off the drawing title in the title block; untick it if the title block was read wrong.":
    "Uma key plan é só ilustrativa: as salas dela não são desenhadas nem listadas, não entram em nenhum cruzamento TEAP × drawing, e nenhuma NER é criada a partir dela. Lida do drawing title no carimbo; desmarque se o carimbo foi lido errado.",
  "Key plan":
    "Key plan",
  "This page is a key plan — it only illustrates. Place the NER or the Wi-Fi point on the detail sheet, and point at it here with *NER.":
    "Esta página é uma key plan — só ilustra. Coloque a NER ou o ponto Wi-Fi na folha de detalhe e aponte para ela aqui com *NER.",
  "This page is a key plan: it only illustrates. Its rooms are not drawn or listed and take part in no TEAP × drawing crossing, and no NER is created from it. Point at the NERs of the detail sheets with *NER★ and *NER.":
    "Esta página é uma key plan: só ilustra. As salas dela não são desenhadas nem listadas, não entram em nenhum cruzamento TEAP × drawing, e nenhuma NER é criada a partir dela. Aponte para as NERs das folhas de detalhe com *NER★ e *NER.",
  "from the room label":
    "do rótulo da sala",
  "Printed on the drawing as":
    "Impresso no desenho como",
  "Show only these rows — click again to show all":
    "Mostrar só estas linhas — clique de novo para mostrar todas",
  "this page is a key plan — it only illustrates: place a *NER reference here, and the NER itself or the access point on the detail sheet":
    "esta página é uma key plan — só ilustra: coloque aqui uma referência *NER, e a NER em si ou o access point na folha de detalhe",
  "this room is on a key plan, and key plans take part in no TEAP × drawing crossing — choose the room on a detail sheet":
    "esta sala está numa key plan, e key plans não entram em nenhum cruzamento TEAP × drawing — escolha a sala numa folha de detalhe",
  "every room found on the drawing is on a key plan, and key plans take part in no TEAP × drawing crossing; if a page was taken for a key plan by mistake, untick Key plan for it in the Drawing viewer":
    "toda sala encontrada no desenho está numa key plan, e key plans não entram em nenhum cruzamento TEAP × drawing; se uma página foi tomada por key plan por engano, desmarque Key plan para ela no Drawing viewer",
  // 2.14.0 — key-plan ticks on Scale, the NER placing step, the toolbox,
  // sequential names, indoor/outdoor, one AP
  "A NER: named in sequence (NERc_01.1 …, NER_20.1 …) — rename it as you like":
    "Uma NER: nomeada em sequência (NERc_01.1 …, NER_20.1 …) — renomeie como quiser",
  "A key plan has no spaces":
    "Uma key plan não tem espaços",
  "A page ticked loses its spaces and any TEAP tie to them; a page unticked gets its spaces read. The matching runs again.":
    "Uma página marcada perde seus espaços e qualquer vínculo do TEAP com eles; uma página desmarcada tem seus espaços lidos. O matching roda de novo.",
  "After the key plans are ticked and the scales confirmed, place the NERs the drawings state: the team's own annotations first, then the coded rooms — TEC.010 (critical) / TEC.020 (non-critical), or TEC.003.01 / .02 on older books — then the \"Network Equipment Rack\" labels (with or without the \"(NER)\", with their arrows when there are any), then the NER block symbols (the small square with NER inside, read by its shape; non-critical, criticality to confirm). Never on a key plan; a candidate within 12 m of a NER already on the sheet is taken as that NER. Every NER is named in sequence — NERc_01.1, NERc_02.1 … / NER_20.1, NER_21.1 … — with what the sheet printed kept as \"printed as\"; rename them on the NERs screen. Running it again only adds what is still missing; a duplicate is yours to delete in the Drawing viewer.":
    "Depois de marcar as key plans e confirmar as escalas, posicione as NERs que os desenhos declaram: primeiro as anotações da própria equipe, depois as salas com código — TEC.010 (crítica) / TEC.020 (não crítica), ou TEC.003.01 / .02 nos livros antigos — depois os rótulos \"Network Equipment Rack\" (com ou sem o \"(NER)\", com suas setas quando houver), depois os símbolos de bloco NER (o quadradinho com NER dentro, lido pela forma; não crítica, criticidade a confirmar). Nunca numa key plan; um candidato a menos de 12 m de uma NER já na folha é tomado como essa NER. Toda NER é nomeada em sequência — NERc_01.1, NERc_02.1 … / NER_20.1, NER_21.1 … — com o que a folha imprimiu guardado como \"printed as\"; renomeie na tela NERs. Rodar de novo só acrescenta o que ainda falta; uma duplicata é sua para apagar no Drawing viewer.",
  "A Wi-Fi point: it marks a space that has wireless, not an access point count; measured to the NER of its TEAP space; it takes no port — the space's DWISA line is the port":
    "Um ponto Wi-Fi: marca um espaço que tem wireless, não é contagem de access points; medido até a NER do seu espaço TEAP; não ocupa porta — a linha DWISA do espaço é a porta",
  "Apply key-plan ticks":
    "Aplicar marcações de key plan",
  "Before placing":
    "Antes de posicionar",
  "Check them in the Drawing viewer and on the NERs screen; delete any duplicate there.":
    "Confira no Drawing viewer e na tela NERs; apague qualquer duplicata lá.",
  "Click a marker, a space or a named area. Drag an unlocked marker to move it; the change is written to the audit log. The +NER tools place a room the study is about; +TER, +IDF, +COW and +DIVA draw what is in the building and never serve a space. +Wi-Fi places a Wi-Fi point: it marks a space that has wireless, not an access point count; measured to its NER; it takes no port — the DWISA line of its TEAP space is the port. The illustrative tools (violet) are drawn and counted nowhere: *NER★ and *NER place a reference to a NER on a key plan, named after a NER of the register and drawn with its reach circles to this sheet's scale; *TER, *COW and *DIVA do the same for those rooms, without circles; +area draws a named area (BTOC, TER, a compound) — click each corner, double-click or Enter to close it. To take anything back: select it and press Delete (or the Delete button here), or arm the delete tool and click what should go.":
    "Clique num marcador, num espaço ou numa área nomeada. Arraste um marcador destravado para movê-lo; a mudança vai para o registro de auditoria. As ferramentas +NER colocam uma sala que é objeto do estudo; +TER, +IDF, +COW e +DIVA desenham o que existe no prédio e nunca atendem um espaço. +Wi-Fi coloca um ponto Wi-Fi: marca um espaço que tem wireless, não é contagem de access points; medido até a sua NER; não ocupa porta — a linha DWISA do seu espaço TEAP é a porta. As ferramentas ilustrativas (violeta) são desenhadas e não contam em lugar nenhum: *NER★ e *NER colocam uma referência a uma NER numa key plan, com o nome de uma NER do registro e os círculos de alcance na escala desta folha; *TER, *COW e *DIVA fazem o mesmo para essas salas, sem círculos; +area desenha uma área nomeada (BTOC, TER, um compound) — clique em cada canto, duplo clique ou Enter para fechar. Para desfazer qualquer coisa: selecione e pressione Delete (ou o botão Delete aqui), ou arme a ferramenta delete e clique no que deve sair.",
  "Hide the naming reference":
    "Esconder a referência de nomes",
  "Hide the tools":
    "Esconder as ferramentas",
  "Indoor":
    "Interna",
  "Outdoor":
    "Externa",
  "Indoor / outdoor":
    "Interna / externa",
  "Location / space":
    "Local / espaço",
  "NER annotation(s) and":
    "anotação(ões) de NER e",
  "NER naming":
    "Nome da NER",
  "NER room(s) read":
    "sala(s) de NER lida(s)",
  "NER room(s) read — tick the key plans and confirm the scales, then place the NERs on the Scale screen":
    "sala(s) de NER lida(s) — marque as key plans e confirme as escalas, depois posicione as NERs na tela Scale",
  "NER(s) placed":
    "NER(s) posicionada(s)",
  "NERs from the drawing":
    "NERs a partir do desenho",
  "Naming":
    "Nomes",
  "Naming reference":
    "Referência de nomes",
  "Next page":
    "Página seguinte",
  "Previous page":
    "Página anterior",
  "One row per NER, whether it came from the drawing or you drew it — the Origin column says which. Every NER the app creates is named in sequence (NERc_01.1, NERc_02.1 … / NER_20.1, NER_21.1 …); rename it here as you like — one name: renaming a room relabels its marker on the sheet, and the label the drawing printed is kept as \"printed as\". Choosing the criticality confirms it. Indoor / outdoor says where the rack stands and goes to the NERs sheet of the workbook. A TER, an IDF, a COW or a DIVA node is not a row here: it is drawn, moved and renamed in the Drawing viewer and takes part in nothing else.":
    "Uma linha por NER, tenha vindo do desenho ou desenhada por você — a coluna Origin diz qual. Toda NER que o app cria é nomeada em sequência (NERc_01.1, NERc_02.1 … / NER_20.1, NER_21.1 …); renomeie aqui como quiser — um nome só: renomear uma sala troca o rótulo do marcador na folha, e o rótulo que o desenho imprimiu fica guardado como \"printed as\". Escolher a criticidade a confirma. Interna / externa diz onde o rack fica e vai para a aba NERs da planilha. Uma TER, um IDF, um COW ou um DIVA node não é linha aqui: é desenhado, movido e renomeado no Drawing viewer e não participa de mais nada.",
  "Place NERs from the drawing":
    "Posicionar NERs a partir do desenho",
  "Place the NERs the drawings state? The team's annotations first, then the TEC.010 / TEC.020 (or TEC.003.01 / .02) rooms, then the \"Network Equipment Rack\" labels, then the NER block symbols — never on a key plan, never where a NER already is. Every one is named in sequence (NERc_01.1 …, NER_20.1 …) for you to rename. Running it again only adds what is still missing.":
    "Posicionar as NERs que os desenhos declaram? Primeiro as anotações da equipe, depois as salas TEC.010 / TEC.020 (ou TEC.003.01 / .02), depois os rótulos \"Network Equipment Rack\", depois os símbolos de bloco NER — nunca numa key plan, nunca onde já há uma NER. Cada uma é nomeada em sequência (NERc_01.1 …, NER_20.1 …) para você renomear. Rodar de novo só acrescenta o que ainda falta.",
  // 2.19.0 — access points from the TEAP; reference labels two points larger
  "Wi-Fi from the TEAP":
    "Wi-Fi a partir do TEAP",
  "Place Wi-Fi from the TEAP":
    "Posicionar Wi-Fi a partir do TEAP",
  "Placing…":
    "Posicionando…",
  "The spaces the TEAP says have wireless (a DWISA line), marked with one Wi-Fi point each where their rooms are, beside the room's label, tied to that space. A Wi-Fi point says the space has wireless; it is not an access point count — the quantity stays on the DWISA line and the number of APs comes from the wireless design. It adds no port: the DWISA line stays the space's wireless port, counted on the NER that serves the space. The distance to the NER is checked from where the point is drawn. Never on a key plan; a space with no room on the drawing gets nothing and stays pending — tie its room first on TEAP × drawing. Running it again never duplicates: it adds only what is missing and takes back extra points it placed itself; points you drew are never removed.":
    "Os espaços que o TEAP diz ter wireless (uma linha DWISA), marcados com um ponto Wi-Fi cada onde estão suas salas, ao lado do rótulo da sala, amarrados a esse espaço. O ponto Wi-Fi diz que o espaço tem wireless; não é contagem de access points — a quantidade continua na linha DWISA e o número de APs vem do design de wireless. Não acrescenta porta: a linha DWISA continua sendo a porta wireless do espaço, contada na NER que atende o espaço. A distância até a NER é conferida a partir de onde o ponto está desenhado. Nunca numa key plan; um espaço sem sala no desenho não recebe nada e fica pendente — amarre a sala antes em TEAP × drawing. Rodar de novo nunca duplica: só acrescenta o que falta e retira os pontos a mais que ele mesmo colocou; pontos desenhados por você nunca são removidos.",
  "Mark the spaces the TEAP says have wireless? One Wi-Fi point for every TEAP space with a DWISA line whose room is on a drawing, beside the room's label and tied to that space. It marks the space, it is not an access point count, and it adds no port — the DWISA line stays the space's wireless port. Never on a key plan; spaces with no room on the drawing get nothing and stay pending. Running it again only adds what is missing and takes back extra points it placed.":
    "Marcar os espaços que o TEAP diz ter wireless? Um ponto Wi-Fi para cada espaço TEAP com linha DWISA cuja sala está num desenho, ao lado do rótulo da sala e amarrado a esse espaço. Ele marca o espaço, não é contagem de access points e não acrescenta porta — a linha DWISA continua sendo a porta wireless do espaço. Nunca numa key plan; espaços sem sala no desenho não recebem nada e ficam pendentes. Rodar de novo só acrescenta o que falta e retira os pontos a mais que ele mesmo colocou.",
  "Wi-Fi point(s) placed in":
    "ponto(s) Wi-Fi posicionado(s) em",
  "space(s)":
    "espaço(s)",
  "space(s) already had their Wi-Fi point":
    "espaço(s) já tinham seu ponto Wi-Fi",
  "space(s) request wireless but have no room on the drawing — left pending":
    "espaço(s) pedem wireless mas não têm sala no desenho — ficam pendentes",
  "space(s) sit on a key plan":
    "espaço(s) está(ão) numa key plan",
  "Check them in the Drawing viewer; drag a point if it sits on something you need to read.":
    "Confira no Drawing viewer; arraste um ponto se ele estiver em cima de algo que você precisa ler.",
  "placed from the TEAP":
    "posicionado a partir do TEAP",
  "from the TEAP":
    "do TEAP",
  "the TEAP space this point was placed for — it stays tied wherever you drag it; change or clear it here if it serves another space":
    "o espaço TEAP para o qual este ponto foi posicionado — continua amarrado onde quer que você o arraste; troque ou limpe aqui se ele atender outro espaço",
  // 2.18.0 — the naming reference panel
  "Principles":
    "Princípios",
  "Show the naming reference":
    "Mostrar a referência de nomes",
  "Show the tools":
    "Mostrar as ferramentas",
  "TEAP tie(s) to a room on a key plan released.":
    "vínculo(s) do TEAP com sala em key plan liberado(s).",
  "The Key plan tick marks a page that only illustrates — a key enlarged plan, the drawing index, the venue information, the abbreviations: no space is read off it, it takes part in no TEAP × drawing crossing and no NER is placed on it. Ticked by default from the title block; change it and press Apply.":
    "A marcação Key plan indica uma página que só ilustra — key enlarged plan, índice de desenhos, informações da venue, abreviações: nenhum espaço é lido dela, ela não entra em nenhum cruzamento TEAP × drawing e nenhuma NER é posicionada nela. Marcada por padrão a partir do carimbo; mude e pressione Apply.",
  "Tools":
    "Ferramentas",
  "Undo ticks":
    "Desfazer marcações",
  "Where the rack stands — it decides the kind of rack the venue is sent. A column of the NERs sheet in the workbook.":
    "Onde o rack fica — decide o tipo de rack enviado para a venue. Uma coluna da aba NERs da planilha.",
  "already had a NER beside them":
    "já tinham uma NER ao lado",
  "created":
    "criada(s)",
  "detail page(s) have no confirmed scale — a NER near an existing one is told apart at 12 m, which needs the scale":
    "página(s) de detalhe sem escala confirmada — uma NER perto de outra é distinguida a 12 m, o que precisa da escala",
  "detail page(s) with no confirmed scale":
    "página(s) de detalhe sem escala confirmada",
  "from the team's annotations":
    "das anotações da equipe",
  "key plan(s)":
    "key plan(s)",
  "last placed":
    "último posicionamento",
  "page(s) changed":
    "página(s) alterada(s)",
  "space(s) read off the pages that are detail sheets again":
    "espaço(s) lido(s) das páginas que voltaram a ser folhas de detalhe",
  "space(s) taken off the key plans":
    "espaço(s) retirado(s) das key plans",
  "you have key-plan ticks not applied yet":
    "há marcações de key plan ainda não aplicadas",
  "— not said —":
    "— não informado —",
  "Wi-Fi — space with wireless":
    "Wi-Fi — espaço com wireless",
  "Wi-Fi": "Wi-Fi",
  // 2.18.1 — deleting a NER deletes it everywhere
  "Delete the NER": "Apagar a NER",
  "It is also drawn on": "Ela também está desenhada em",
  "It leaves every page, the NERs list, the analysis and the export. Restore on the NERs screen (Removed (n)) brings it back.":
    "Ela sai de todas as páginas, da lista de NERs, da análise e da exportação. Restore na tela NERs (Removed (n)) traz de volta.",
  "Delete only this marker of": "Apagar só este marcador de",
  "The NER stays on": "A NER continua em",
  "and in the NERs list.": "e na lista de NERs.",
  "It is the NER's last marker, so the NER leaves the register too.":
    "É o último marcador da NER, então a NER sai do registro também.",
  "removed — it leaves every page, the NERs list and the analysis. Restore on the NERs screen brings it back.":
    "removida — sai de todas as páginas, da lista de NERs e da análise. Restore na tela NERs traz de volta.",
  "Deletes the NER: every page, the NERs list, the analysis and the export. Restore on the NERs screen brings it back.":
    "Apaga a NER: todas as páginas, a lista de NERs, a análise e a exportação. Restore na tela NERs traz de volta.",
  "This NER is drawn on": "Esta NER está desenhada em",
  "pages. Delete removes it from all of them.": "páginas. Delete remove de todas elas.",
  "Delete only this marker": "Apagar só este marcador",
  "For a duplicate drawing of the room on this sheet: this marker goes, the NER stays on its other pages.":
    "Para um desenho duplicado da sala nesta folha: este marcador sai, a NER continua nas outras páginas.",
  "Other NER rows carry the same name": "Outras linhas de NER têm o mesmo nome",
  "They are separate register rows and stay on their pages unless removed too.":
    "São linhas separadas do registro e continuam nas suas páginas se não forem removidas também.",
  "OK: remove them as well. Cancel: remove only this row.":
    "OK: remove essas também. Cancelar: remove só esta linha.",
  "row(s) of the same name": "linha(s) com o mesmo nome",
  "removed — it leaves every page, the analysis and the export; Restore brings it back":
    "removida — sai de todas as páginas, da análise e da exportação; Restore traz de volta",
  // 3.0.0
  "Space code": "Space code",
  "The room's space code as the AAM or the VDB writes it (TEC.010-001). Filled from the code printed on the drawing; type to correct it. Column C of the NERs sheet in the workbook.":
    "O código do espaço da sala como o AAM ou o VDB escreve (TEC.010-001). Vem do código impresso no desenho; digite para corrigir. Coluna C da aba de NERs da planilha.",
  "Space code (AAM / VDB) — goes to the workbook": "Space code (AAM / VDB) — vai para a planilha",
  "served — room not confirmed": "atendidas — sala não confirmada",
  "Counted on the nearest NER from the room the matcher found; confirm the room on TEAP × drawing when you have checked it":
    "Contadas na NER mais próxima a partir da sala que o matcher achou; confirme a sala em TEAP × drawing depois de conferir",
  "room not confirmed": "sala não confirmada",
  "A room the matcher found is served by the nearest NER before you confirm it; the row says the room is not confirmed until you do.":
    "Uma sala que o matcher achou é atendida pela NER mais próxima antes de você confirmar; a linha diz que a sala não está confirmada até você confirmar.",
  // 4.0.0 — the TEAP is the only source of ports; placing never duplicates
  "extra Wi-Fi point(s) taken back (one per space)":
    "ponto(s) Wi-Fi a mais retirado(s) (um por espaço)",
  "Wi-Fi point(s) drawn by hand beyond one per space — kept, check them":
    "ponto(s) Wi-Fi desenhado(s) à mão além de um por espaço — mantidos, confira",
  "TEAP space":
    "Espaço TEAP",
  "Place NERs from the drawing is already running for this project — wait for it to finish":
    "Posicionar NERs a partir do desenho já está rodando neste projeto — aguarde terminar",
  "Place Wi-Fi from the TEAP is already running for this project — wait for it to finish":
    "Posicionar Wi-Fi a partir do TEAP já está rodando neste projeto — aguarde terminar",
  "Forgot your password?":
    "Esqueceu a senha?",
  "Ask an administrator of this installation: Account & security → Reset password. You choose a new password at the next sign-in.":
    "Peça a um administrador desta instalação: Account & security → Reset password. Você escolhe uma senha nova no próximo login.",
  "No administrator, or you are the administrator? On the computer where the app is installed, open the app's folder and run the reset tool. It lists the accounts, asks which one and the new password twice, and works with the app running:":
    "Não há administrador, ou o administrador é você? No computador onde o app está instalado, abra a pasta do app e rode a ferramenta de reset. Ela lista as contas, pergunta qual e a senha nova duas vezes, e funciona com o app aberto:",
  // --- 4.2.0 -----------------------------------------------------------------
  "changed since the last run": "alterado desde a última execução",
  "Something changed after the last run. The exports run the analysis again by themselves; press Run analysis to see the new figures here.":
    "Algo mudou depois da última execução. As exportações rodam a análise de novo sozinhas; pressione Run analysis para ver os números novos aqui.",
  "the analysis was run again first:": "a análise foi executada de novo antes:",
  "change(s) after the last run": "alteração(ões) depois da última execução",
  "is already the name of another NER": "já é o nome de outra NER",
  "Is it the same NER? OK makes the two one NER, with every marker of both. Cancel keeps the current name — choose another one.":
    "É a mesma NER? OK junta as duas numa só NER, com todos os marcadores das duas. Cancelar mantém o nome atual — escolha outro.",
  "Sheet this shaft connects to — the series and the page as the page selector shows them (600 12), or the drawing number":
    "Folha à qual este shaft se liga — a série e a página como o seletor de páginas mostra (600 12), ou o número do desenho",
  "No sheet answers to": "Nenhuma folha corresponde a",
  "Type the series and the page, e.g. 600 12, or the drawing number.": "Digite a série e a página, por exemplo 600 12, ou o número do desenho.",
  "Type a page number of this drawing.": "Digite um número de página deste desenho.",
  "Shaft registered between": "Shaft registrado entre",
  // 4.3.0 — the naming panel reads its table from the private reference folder
  "The naming reference, for reference only — it decides nothing":
    "A referência de nomes, só para consulta — não decide nada",
  "The app names every NER it creates in sequence: NERc_01.1, NERc_02.1 … for critical rooms and NER_20.1, NER_21.1 … for non-critical ones. Rename each one as your project's naming document says; the name you give a NER is the name.":
    "O app nomeia cada NER que cria em sequência: NERc_01.1, NERc_02.1 … para salas críticas e NER_20.1, NER_21.1 … para as não críticas. Renomeie cada uma como diz o documento de nomes do seu projeto; o nome que você dá a uma NER é o nome.",
  "No naming reference is bundled with this copy. A team can add its own naming document to the package's private reference folder; it is shown here for reference only.":
    "Nenhuma referência de nomes vem com esta cópia. Uma equipe pode acrescentar o próprio documento de nomes na pasta de referência privada do pacote; ele aparece aqui só para consulta.",
  "Loading…": "Carregando…",
  "in the Drawing viewer": "no Drawing viewer",
  "Show the legend": "Mostrar a legenda",
  "Hide the legend": "Recolher a legenda",
  "hide": "recolher",
  "Show the menu": "Mostrar o menu",
  "Hide the menu": "Recolher o menu",
  "Already set to — none —; Undo takes it back": "Já está como — none —; o Undo desfaz",
  "This space is not on this drawing — set it to — none —": "Este espaço não está neste desenho — marcar como — none —",
  "identical name, confirmed by the matcher": "nome idêntico, confirmado pelo matcher",
  "Confirmed by you": "Confirmado por você",
  "Confirmed by the matcher — an exact match": "Confirmado pelo matcher — correspondência exata",
  "exact": "exato",
  // 4.5.0 — indoor / outdoor for each Wi-Fi point
  "Where the service is given: indoor (a covered area) or outdoor (an open area). A column of the Wireless points sheet in the workbook.":
    "Onde o serviço será prestado: indoor (área coberta) ou outdoor (área aberta). Uma coluna da aba Wireless points da planilha.",
};
