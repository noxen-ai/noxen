"""Test suite per core/research/treesitter_parser.py — Step M.1."""

import pytest
from pathlib import Path

from core.research.treesitter_parser import (
    TreeSitterParser,
    ParsedFile,
    ParsedFunction,
    ParsedClass,
    ParsedImport,
    SUPPORTED_LANGUAGES,
)


# ── Code fixtures ───────────────────────────────────────────────────

PYTHON_CODE = '''\
import os
from typing import List

class MyService:
    """Service docstring."""

    def __init__(self, name: str):
        self.name = name

    async def process(self, items: List[str]) -> dict:
        """Process items."""
        if not items:
            return {}
        return {"count": len(items)}

def standalone_func(x: int, y: int = 0) -> int:
    return x + y
'''

JAVASCRIPT_CODE = '''\
import express from 'express';

export function hello() {
    return 'world';
}

export class UserService {
    constructor(http) {
        this.http = http;
    }
    async getUser(id) {
        return await fetch(id);
    }
}

const greet = (name) => {
    return `Hello ${name}`;
};
'''

TYPESCRIPT_CODE = '''\
import { Injectable } from '@angular/core';
import axios from 'axios';

export class UserService {
    private baseUrl: string;

    constructor(private http: HttpClient) {
        this.baseUrl = '/api/users';
    }

    async getUser(id: number): Promise<UserData> {
        const response = await axios.get(`${this.baseUrl}/${id}`);
        return response.data;
    }
}
'''

JAVA_CODE = '''\
package com.example;

import java.util.List;
import org.springframework.stereotype.Service;

@Service
public class OrderService extends BaseService implements Runnable {

    private final OrderRepository repository;

    public OrderService(OrderRepository repository) {
        this.repository = repository;
    }

    public List<Order> findByUser(Long userId) {
        if (userId == null) {
            throw new IllegalArgumentException("userId required");
        }
        return repository.findByUserId(userId);
    }
}
'''

GO_CODE = '''\
package main

import (
    "fmt"
    "net/http"
)

type Handler struct {
    db *Database
}

func (h *Handler) GetUser(w http.ResponseWriter, r *http.Request) {
    id := r.URL.Query().Get("id")
    if id == "" {
        http.Error(w, "missing id", 400)
        return
    }
    fmt.Fprintf(w, "user: %s", id)
}

func NewHandler(db *Database) *Handler {
    return &Handler{db: db}
}
'''


# ── Fixtures ────────────────────────────────────────────────────────

@pytest.fixture
def parser():
    return TreeSitterParser()


# ── Test Python ─────────────────────────────────────────────────────

def test_python_classes(parser):
    """parse_file() su Python trova 1 classe MyService."""
    result = parser.parse_file(Path("test.py"), PYTHON_CODE)
    assert result is not None
    class_names = [c.name for c in result.classes]
    assert "MyService" in class_names
    assert len(result.classes) == 1


def test_python_class_methods(parser):
    """parse_file() trova 2 metodi in MyService."""
    result = parser.parse_file(Path("test.py"), PYTHON_CODE)
    svc = next(c for c in result.classes if c.name == "MyService")
    assert "__init__" in svc.methods
    assert "process" in svc.methods
    assert len(svc.methods) == 2


def test_python_standalone_function(parser):
    """parse_file() trova funzione standalone."""
    result = parser.parse_file(Path("test.py"), PYTHON_CODE)
    func_names = [f.name for f in result.functions]
    assert "standalone_func" in func_names


def test_python_methods_in_functions(parser):
    """parse_file() trova anche metodi come functions."""
    result = parser.parse_file(Path("test.py"), PYTHON_CODE)
    func_names = [f.name for f in result.functions]
    # Methods are also extracted as functions
    assert "__init__" in func_names
    assert "process" in func_names
    assert "standalone_func" in func_names


def test_python_imports(parser):
    """parse_file() trova 2 import."""
    result = parser.parse_file(Path("test.py"), PYTHON_CODE)
    modules = [i.module for i in result.imports]
    assert "os" in modules
    assert "typing" in modules


def test_python_async_detection(parser):
    """process() e' marcata come is_async."""
    result = parser.parse_file(Path("test.py"), PYTHON_CODE)
    process_func = next(f for f in result.functions if f.name == "process")
    assert process_func.is_async is True


def test_python_non_async(parser):
    """standalone_func non e' async."""
    result = parser.parse_file(Path("test.py"), PYTHON_CODE)
    sf = next(f for f in result.functions if f.name == "standalone_func")
    assert sf.is_async is False


def test_python_class_docstring(parser):
    """MyService ha docstring."""
    result = parser.parse_file(Path("test.py"), PYTHON_CODE)
    svc = next(c for c in result.classes if c.name == "MyService")
    assert svc.docstring is not None
    assert "Service docstring" in svc.docstring


def test_python_func_params(parser):
    """standalone_func ha params [x, y]."""
    result = parser.parse_file(Path("test.py"), PYTHON_CODE)
    sf = next(f for f in result.functions if f.name == "standalone_func")
    assert "x" in sf.params
    assert "y" in sf.params


def test_python_return_type(parser):
    """standalone_func ha return_type int."""
    result = parser.parse_file(Path("test.py"), PYTHON_CODE)
    sf = next(f for f in result.functions if f.name == "standalone_func")
    assert sf.return_type is not None
    assert "int" in sf.return_type


def test_python_complexity(parser):
    """process() ha complexity > 1 (ha if)."""
    result = parser.parse_file(Path("test.py"), PYTHON_CODE)
    process_func = next(f for f in result.functions if f.name == "process")
    assert process_func.complexity > 1


def test_python_from_import(parser):
    """from typing import List e' is_from=True."""
    result = parser.parse_file(Path("test.py"), PYTHON_CODE)
    typing_imp = next(i for i in result.imports if i.module == "typing")
    assert typing_imp.is_from is True


def test_python_line_count(parser):
    """parse_file() conta le righe."""
    result = parser.parse_file(Path("test.py"), PYTHON_CODE)
    assert result.lines > 10


# ── Test JavaScript ─────────────────────────────────────────────────

def test_js_function(parser):
    """parse_file() trova funzione hello."""
    result = parser.parse_file(Path("test.js"), JAVASCRIPT_CODE)
    assert result is not None
    func_names = [f.name for f in result.functions]
    assert "hello" in func_names


def test_js_class(parser):
    """parse_file() trova classe UserService."""
    result = parser.parse_file(Path("test.js"), JAVASCRIPT_CODE)
    class_names = [c.name for c in result.classes]
    assert "UserService" in class_names


def test_js_class_methods(parser):
    """parse_file() trova metodi di UserService."""
    result = parser.parse_file(Path("test.js"), JAVASCRIPT_CODE)
    svc = next(c for c in result.classes if c.name == "UserService")
    assert "constructor" in svc.methods
    assert "getUser" in svc.methods


def test_js_async_method(parser):
    """getUser e' async."""
    result = parser.parse_file(Path("test.js"), JAVASCRIPT_CODE)
    gu = next(f for f in result.functions if f.name == "getUser")
    assert gu.is_async is True


def test_js_import(parser):
    """parse_file() trova import da 'express'."""
    result = parser.parse_file(Path("test.js"), JAVASCRIPT_CODE)
    modules = [i.module for i in result.imports]
    assert "express" in modules


def test_js_arrow_function(parser):
    """parse_file() trova arrow function greet."""
    result = parser.parse_file(Path("test.js"), JAVASCRIPT_CODE)
    func_names = [f.name for f in result.functions]
    assert "greet" in func_names


# ── Test TypeScript ─────────────────────────────────────────────────

def test_ts_class(parser):
    """parse_file() trova classe TypeScript."""
    result = parser.parse_file(Path("test.ts"), TYPESCRIPT_CODE)
    assert result is not None
    class_names = [c.name for c in result.classes]
    assert "UserService" in class_names


def test_ts_imports(parser):
    """parse_file() trova import TypeScript."""
    result = parser.parse_file(Path("test.ts"), TYPESCRIPT_CODE)
    modules = [i.module for i in result.imports]
    assert "@angular/core" in modules
    assert "axios" in modules


def test_ts_async_method(parser):
    """getUser TS e' async."""
    result = parser.parse_file(Path("test.ts"), TYPESCRIPT_CODE)
    gu = next((f for f in result.functions if f.name == "getUser"), None)
    assert gu is not None
    assert gu.is_async is True


# ── Test Java ───────────────────────────────────────────────────────

def test_java_class(parser):
    """parse_file() trova classe Java."""
    result = parser.parse_file(Path("test.java"), JAVA_CODE)
    assert result is not None
    class_names = [c.name for c in result.classes]
    assert "OrderService" in class_names


def test_java_class_bases(parser):
    """OrderService estende BaseService e implementa Runnable."""
    result = parser.parse_file(Path("test.java"), JAVA_CODE)
    cls = next(c for c in result.classes if c.name == "OrderService")
    assert "BaseService" in cls.base_classes
    assert "Runnable" in cls.base_classes


def test_java_imports(parser):
    """parse_file() trova import Java."""
    result = parser.parse_file(Path("test.java"), JAVA_CODE)
    modules = [i.module for i in result.imports]
    assert "java.util.List" in modules


def test_java_methods(parser):
    """parse_file() trova metodi Java."""
    result = parser.parse_file(Path("test.java"), JAVA_CODE)
    func_names = [f.name for f in result.functions]
    assert "findByUser" in func_names


def test_java_method_params(parser):
    """findByUser ha param userId."""
    result = parser.parse_file(Path("test.java"), JAVA_CODE)
    fb = next(f for f in result.functions if f.name == "findByUser")
    assert "userId" in fb.params


def test_java_constructor(parser):
    """parse_file() trova constructor Java."""
    result = parser.parse_file(Path("test.java"), JAVA_CODE)
    func_names = [f.name for f in result.functions]
    assert "OrderService" in func_names


# ── Test Go ─────────────────────────────────────────────────────────

def test_go_struct(parser):
    """parse_file() trova struct Go."""
    result = parser.parse_file(Path("test.go"), GO_CODE)
    assert result is not None
    class_names = [c.name for c in result.classes]
    assert "Handler" in class_names


def test_go_functions(parser):
    """parse_file() trova funzioni Go."""
    result = parser.parse_file(Path("test.go"), GO_CODE)
    func_names = [f.name for f in result.functions]
    assert "GetUser" in func_names
    assert "NewHandler" in func_names


def test_go_imports(parser):
    """parse_file() trova import Go."""
    result = parser.parse_file(Path("test.go"), GO_CODE)
    modules = [i.module for i in result.imports]
    assert "fmt" in modules
    assert "net/http" in modules


def test_go_complexity(parser):
    """GetUser ha complexity > 1."""
    result = parser.parse_file(Path("test.go"), GO_CODE)
    gu = next(f for f in result.functions if f.name == "GetUser")
    assert gu.complexity > 1


# ── Test Edge Cases ─────────────────────────────────────────────────

def test_unsupported_extension(parser):
    """Estensione non supportata ritorna None."""
    result = parser.parse_file(Path("test.xyz"), "some content")
    assert result is None


def test_empty_file(parser):
    """File vuoto ritorna ParsedFile con liste vuote."""
    result = parser.parse_file(Path("test.py"), "")
    assert result is not None
    assert result.functions == []
    assert result.classes == []
    assert result.imports == []
    assert result.lines == 1


def test_syntax_errors(parser):
    """File con errori di sintassi ha parse_errors > 0."""
    bad_code = "def foo(\n  class Bar{{\n  import ;"
    result = parser.parse_file(Path("test.py"), bad_code)
    assert result is not None
    assert result.parse_errors > 0


def test_encoding_resilience(parser):
    """File con caratteri non-standard non crasha."""
    code = "def foo():\n    x = 'caf\u00e9'\n    pass\n"
    result = parser.parse_file(Path("test.py"), code)
    assert result is not None
    func_names = [f.name for f in result.functions]
    assert "foo" in func_names


def test_parse_errors_zero_on_valid(parser):
    """File valido ha 0 parse errors."""
    result = parser.parse_file(Path("test.py"), PYTHON_CODE)
    assert result.parse_errors == 0


# ── Test SUPPORTED_LANGUAGES constant ───────────────────────────────

def test_supported_languages():
    """SUPPORTED_LANGUAGES ha le estensioni principali."""
    assert ".py" in SUPPORTED_LANGUAGES
    assert ".js" in SUPPORTED_LANGUAGES
    assert ".ts" in SUPPORTED_LANGUAGES
    assert ".java" in SUPPORTED_LANGUAGES
    assert ".go" in SUPPORTED_LANGUAGES


# ── Test detect_language ────────────────────────────────────────────

def test_detect_python(parser):
    assert parser._detect_language(Path("foo.py")) == "python"

def test_detect_js(parser):
    assert parser._detect_language(Path("foo.js")) == "javascript"

def test_detect_ts(parser):
    assert parser._detect_language(Path("foo.ts")) == "typescript"

def test_detect_tsx(parser):
    assert parser._detect_language(Path("foo.tsx")) == "tsx"

def test_detect_unknown(parser):
    assert parser._detect_language(Path("foo.xyz")) is None


# ── Test count_errors ───────────────────────────────────────────────

def test_count_errors_clean(parser):
    """Nessun errore su codice valido."""
    result = parser.parse_file(Path("test.py"), "x = 1\n")
    assert result.parse_errors == 0
