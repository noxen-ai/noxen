# Repo Analyzer Migration: regex → tree-sitter

**Data**: 2026-03-30
**Stato**: Analisi pre-migrazione (Step M.0)

## Metodi che usano regex

| Metodo | Linguaggio | Regex usati | Limitazioni |
|--------|-----------|------------|-------------|
| `_analyze_python()` | Python | 3 regex (func, class, import) | Non distingue stringhe/commenti; class regex richiede `^class` (no indented); docstring solo single-line `"""..."""` |
| `_analyze_js_ts()` | JS/TS | 5 regex (3 func patterns, class, import) | Arrow functions parziali; non cattura method_definition dentro classi; no interface/type |
| `_analyze_go()` | Go | 2 regex (func, import) | Import match fragile (lookback 10 righe); no struct detection |
| `_analyze_java()` | Java | 3 regex (class, method, import) | No inner class; no interface; constructor non catturato se non ha tipo ritorno esplicito |
| `_detect_frameworks()` | All | 18 regex patterns | OK, rimarranno regex — sono text-match, non AST |
| `_extract_endpoints()` | All | 10 regex patterns | OK, rimarranno regex — sono text-match in decorator/call patterns |

## Metodi che NON cambiano

- `_clone()` — git subprocess, nessun regex
- `_cleanup()` — shutil.rmtree
- `_detect_language()` — extension map
- `_detect_frameworks()` — text pattern match, non serve AST
- `_extract_endpoints()` — text pattern match su decoratori/routes
- `clone_and_analyze()` — orchestrator, chiama `_analyze()`
- `_analyze()` — file walker, chiamera' TreeSitterParser internamente

## Test impact analysis

### Test che non cambiano (interfaccia/infra)
- `test_repo_analysis_defaults` — dataclass defaults
- `test_function_info_defaults` — dataclass defaults
- `test_class_info_defaults` — dataclass defaults
- `test_import_info_defaults` — dataclass defaults
- `test_lang_extensions_coverage` — constants
- `test_skip_dirs_has_common` — constants
- `test_framework_patterns_coverage` — constants
- `test_detect_language_*` (4 test) — extension map
- `test_detect_fastapi` — framework regex (unchanged)
- `test_detect_express` — framework regex (unchanged)
- `test_extract_fastapi_endpoints` — endpoint regex (unchanged)
- `test_extract_express_endpoints` — endpoint regex (unchanged)
- `test_important_files_detected` — file walker
- `test_skips_pycache` — dir filter
- `test_file_count` — file counter
- `test_total_lines` — line counter
- `test_languages_count` — language counter
- `test_skips_large_files` — size filter
- `test_clone_and_analyze_*` (4 test) — mocked clone
- `test_cleanup_*` (2 test) — cleanup
- `test_analyzer_constructor_*` (2 test) — constructor

### Test che potrebbero migliorare con tree-sitter
- `test_analyze_python_functions`: tree-sitter troverà anche `get_user` (metodo dentro classe) — regex attuale lo trova già perché matcha `def` indentato
- `test_analyze_python_async_detection`: tree-sitter è più preciso su async — potrebbe trovare esattamente 3 (create_user, list_users, add_user)
- `test_analyze_python_classes`: invariato, 1 classe
- `test_analyze_python_imports`: tree-sitter troverà `from fastapi import FastAPI` e `import os` — stesso risultato
- `test_analyze_python_decorators`: tree-sitter è più preciso su decoratori — troverà sicuramente i 2 decorati
- `test_analyze_js_functions`: tree-sitter troverà `hello` — stesso risultato
- `test_analyze_js_imports`: invariato
- `test_analyze_go_functions`: invariato (main, HandleRequest)
- `test_analyze_go_imports`: invariato (fmt, net/http)
- `test_analyze_java_classes`: tree-sitter troverà superclass + interfaces — potrebbe essere più preciso
- `test_analyze_java_methods`: tree-sitter troverà run, getName + possibilmente il constructor
- `test_analyze_java_imports`: invariato

### Conclusione
Nessun test dovrebbe peggiorare. Alcuni potrebbero trovare PIU' risultati. I test usano `assert X in names` o `assert len(X) >= N`, quindi sono robusti rispetto a risultati aggiuntivi.

## Dipendenze tree-sitter

```
tree-sitter>=0.25.0          # core (upgraded from 0.24.0)
tree-sitter-python>=0.25.0   # NEW
tree-sitter-javascript>=0.25.0  # NEW
tree-sitter-typescript>=0.23.0  # NEW
tree-sitter-java>=0.23.0     # NEW
tree-sitter-go>=0.25.0       # NEW
```

API: `Language(module.language())` + `Parser(language)` + `parser.parse(bytes)`
TS variant: `Language(tsts.language_typescript())` / `Language(tsts.language_tsx())`

## Piano migrazione

1. **M.1**: Crea `treesitter_parser.py` con `TreeSitterParser` class
2. **M.2**: Inietta `TreeSitterParser` in `RepoAnalyzer._analyze()`, sostituisci i 4 metodi regex
3. **M.3**: Aggiorna test se necessario (aspettarsi >= risultati)
