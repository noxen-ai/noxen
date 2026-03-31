# Migrazione Repo Analyzer: regex -> tree-sitter

**Data**: 2026-03-30
**Stato**: COMPLETATA

## Test count

| Fase | Test totali |
|------|------------|
| Prima della migrazione | 430 |
| Dopo la migrazione | 474 (+44 nuovi test TreeSitterParser) |
| Test originali repo_analyzer | 41/41 passano senza modifiche |

## Miglioramenti di accuratezza

### Python
- **Prima (regex)**: trovava funzioni con `^(\s*)(async\s+)?def\s+(\w+)\s*\(` — funzionava ma fragile su edge case (commenti, stringhe multilinea contenenti `def`)
- **Dopo (tree-sitter)**: AST reale — trova `function_definition`, `async_function_definition`, gestisce correttamente scope/nesting, decoratori come nodi AST separati
- **Miglioramento**: docstring estratte dall'AST (primo `expression_statement > string` nel body), parametri con tipo, return type, complessita' ciclomatica

### JavaScript/TypeScript
- **Prima**: 3 regex per function_declaration, arrow, const assignment — non catturava `method_definition` dentro classi
- **Dopo**: tree-sitter cattura `function_declaration`, `method_definition`, `arrow_function`, `variable_declarator` con function value
- **Miglioramento**: cattura metodi di classe (constructor, getUser), arrow functions assegnate a variabili

### Go
- **Prima**: regex `func\s+...` + fragile lookback per import
- **Dopo**: AST `function_declaration`, `method_declaration`, `import_spec` strutturato
- **Miglioramento**: import extraction precisa (no false positive su stringhe quotate), struct detection come `ParsedClass`

### Java
- **Prima**: regex per class/method/import — non catturava constructor, no inner class, interface con `implements` fragile
- **Dopo**: AST `class_declaration > body > method_declaration/constructor_declaration`, `superclass`, `super_interfaces > type_list`
- **Miglioramento**: cattura constructor, interfacce implementate, tipi ritorno, parametri con nome

## Nuove feature (tree-sitter only)

| Feature | Descrizione |
|---------|------------|
| `ParsedFunction.params` | Lista nomi parametri (filtra self/cls per Python) |
| `ParsedFunction.return_type` | Tipo ritorno estratto dall'AST |
| `ParsedFunction.complexity` | Complessita' ciclomatica (if/for/while/case/and/or) |
| `ParsedClass.methods` | Lista nomi metodi nella classe |
| `ParsedClass.decorators` | Decoratori della classe (Python) |
| `ParsedFile.parse_errors` | Nodi ERROR nell'AST — detecta file problematici |
| TypeScript/TSX | Supporto nativo (prima mappato a JavaScript) |

## Linguaggi supportati

| Linguaggio | Prima | Dopo |
|-----------|-------|------|
| Python | regex | tree-sitter |
| JavaScript | regex | tree-sitter |
| TypeScript | regex (come JS) | tree-sitter nativo |
| TSX | non supportato | tree-sitter |
| Java | regex | tree-sitter |
| Go | regex | tree-sitter |
| Rust, Ruby, PHP, C#, etc. | solo file count | solo file count (invariato) |

## Dipendenze aggiunte

```
tree-sitter>=0.25.0          (aggiornato da 0.24.0)
tree-sitter-python>=0.25.0   (NUOVO)
tree-sitter-javascript>=0.25.0 (NUOVO)
tree-sitter-typescript>=0.23.0 (NUOVO)
tree-sitter-java>=0.23.0     (NUOVO)
tree-sitter-go>=0.25.0       (NUOVO)
```

Nota: `tree-sitter-languages` (pacchetto all-in-one) NON disponibile per Python 3.13. Usati pacchetti individuali con API `Language(module.language())`.

## Architettura

```
RepoAnalyzer
├── _analyze_with_treesitter()  ← NUOVO, sostituisce 4 metodi regex
│   └── TreeSitterParser.parse_file()
│       ├── _extract_python_functions/classes/imports
│       ├── _extract_js_functions/classes/imports
│       ├── _extract_go_functions/structs/imports
│       └── _extract_java_functions/classes/imports
├── _detect_frameworks()        ← invariato (regex, text match)
└── _extract_endpoints()        ← invariato (regex, route patterns)
```

## Note per Fase 4

- TreeSitterParser e' injectable via `parser=` nel constructor di RepoAnalyzer
- Complessita' ciclomatica disponibile per quality analysis
- Parse errors count utile per detectare file corrotti/minificati
- Estendibile ad altri linguaggi aggiungendo `tree-sitter-{lang}` package
