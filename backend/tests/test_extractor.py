from __future__ import annotations

from app.parsing.extractor import extract_file


def _ex(path: str, key: str, code: str, lang: str | None = None):  # type: ignore[no-untyped-def]
    return extract_file(path, key, code.encode(), lang or key)


def _by_name(res, name: str):  # type: ignore[no-untyped-def]
    return next(s for s in res.symbols if s.name == name)


def test_python() -> None:
    code = '''
import os
from .util import helper as h
from pkg.mod import a, b

@app.route("/x")
async def f(a: int, b=2) -> str:
    """Doc string."""
    x = h(a)
    return os.path.join(x)

class A(Base):
    def m(self):
        return self.n()

if __name__ == "__main__":
    f(1)
'''
    res = _ex("app/main.py", "python", code)
    f = _by_name(res, "f")
    assert (f.start_line, f.end_line) == (6, 10)
    assert f.params == "(a: int, b=2)"
    assert f.returns == "str"
    assert f.docstring == "Doc string."
    assert f.decorators == ['app.route("/x")']
    assert [(c.receiver, c.name) for c in f.calls] == [(None, "h"), ("os.path", "join")]
    a = _by_name(res, "A")
    assert a.kind == "class"
    m = _by_name(res, "m")
    assert m.kind == "method" and m.qualname == "A.m" and m.parent == a.id
    assert m.calls[0].receiver == "self" and m.calls[0].name == "n"
    mods = [(i.module, i.names, i.alias) for i in res.file.imports]
    assert mods == [("os", [], None), (".util", ["helper"], None), ("pkg.mod", ["a", "b"], None)]
    assert res.file.main_guards[0].start_line == 16
    assert res.file.top_level_calls[0].name == "f"


def test_javascript() -> None:
    code = """
import x, {y as z} from './util';
const r = require('express');
export default function f(a, b) { return g(a) + obj.m(b); }
const h = async (q) => { await fetch(q); };
class C extends D { constructor(){ super(); } m() { return this.k(); } }
app.get('/p', (req, res) => res.send(1));
module.exports = { f, handler: async () => { run(); } };
new Foo(1);
"""
    res = _ex("src/index.js", "javascript", code)
    names = {s.name: s for s in res.symbols}
    assert set(names) == {"f", "h", "C", "constructor", "m", "handler"}
    assert names["f"].is_exported and names["f"].params == "(a, b)"
    assert [c.name for c in names["f"].calls] == ["g", "m"]
    assert names["m"].kind == "method" and names["m"].qualname == "C.m"
    assert [c.name for c in names["handler"].calls] == ["run"]
    imports = [(i.module, i.names) for i in res.file.imports]
    assert imports == [("./util", ["x", "z"]), ("express", ["r"])]
    top = [(c.receiver, c.name) for c in res.file.top_level_calls]
    assert ("app", "get") in top and ("res", "send") in top and (None, "Foo") in top


def test_tsx() -> None:
    code = """
import type {T} from "./t";
export const Comp: React.FC<P> = ({x}) => { const [s, set] = useState(0); return <div onClick={() => go(x)}>{s}</div>; };
export async function load(id: string): Promise<T> { return await api.get<T>(id); }
interface I { m(): void }
export class Svc { private n = 1; run(): number { return this.n; } handle = (e: Event) => { this.run(); } }
"""
    res = _ex("src/App.tsx", "tsx", code, "typescript")
    names = {s.name: s for s in res.symbols}
    assert {"Comp", "load", "Svc", "run", "handle"} <= set(names)
    assert "m" not in names  # interface method signatures are not implementations
    assert names["load"].returns == "Promise<T>"
    assert names["load"].params == "(id: string)"
    assert [c.name for c in names["load"].calls] == ["get"]
    assert names["Comp"].is_exported
    assert [c.name for c in names["Comp"].calls] == ["useState", "go"]
    assert names["handle"].kind == "method" and names["handle"].calls[0].receiver == "this"


def test_java() -> None:
    code = """
package a.b;
import java.util.List;
import a.b.c.D;
@RestController
public class Foo extends Bar {
  private final D d;
  /** Builds Foo. */
  public Foo(D d) { this.d = d; }
  @GetMapping("/x")
  public List<String> get(int n) { return d.list(n); }
  public static void main(String[] args) { new Foo(null).get(1); Util.run(); }
}
"""
    res = _ex("src/Foo.java", "java", code)
    names = {s.name: s for s in res.symbols if s.kind != "class"}
    assert next(s for s in res.symbols if s.kind == "class").name == "Foo"
    ctor = next(s for s in res.symbols if s.kind == "method" and s.name == "Foo")
    assert ctor.docstring == "Builds Foo."
    assert names["get"].decorators == ['GetMapping("/x")']
    assert names["get"].returns == "List<String>"
    assert [(c.receiver, c.name) for c in names["get"].calls] == [("d", "list")]
    assert [c.name for c in names["main"].calls] == ["get", "Foo", "run"]
    assert [i.module for i in res.file.imports] == ["java.util.List", "a.b.c.D"]


def test_go() -> None:
    code = """
package main
import ("fmt"; h "example.com/m/handlers")
type S struct { N int }
// M does things.
func (s *S) M(a int) (int, error) { return helper(a), nil }
func helper(a int) int { fmt.Println(a); return a }
func main() { s := &S{}; s.M(1); http.ListenAndServe(":80", nil); h.Run() }
"""
    res = _ex("cmd/main.go", "go", code)
    names = {s.name: s for s in res.symbols}
    assert names["M"].kind == "method" and names["M"].qualname == "S.M"
    assert names["M"].docstring == "M does things."
    assert names["M"].returns == "(int, error)"
    assert [c.name for c in names["main"].calls] == ["M", "ListenAndServe", "Run"]
    assert [(i.module, i.alias) for i in res.file.imports] == [
        ("fmt", None),
        ("example.com/m/handlers", "h"),
    ]
    assert names["helper"].is_exported is False and names["M"].is_exported


def test_c_and_cpp() -> None:
    c_code = """
#include <stdio.h>
#include "util.h"
static int helper(int a) { return a * 2; }
int main(int argc, char **argv) { printf("%d", helper(argc)); return 0; }
"""
    res = _ex("src/main.c", "c", c_code)
    names = {s.name: s for s in res.symbols}
    assert set(names) == {"helper", "main"}
    assert names["main"].params == "(int argc, char **argv)"
    assert [c.name for c in names["main"].calls] == ["printf", "helper"]
    assert [i.module for i in res.file.imports] == ["stdio.h", "util.h"]

    cpp_code = """
#include "a.hpp"
namespace ns {
class K : public B { public: int m(int a) const; void n(); };
int K::m(int a) const { return helper(a) + this->n(); }
}
int main() { ns::K k; k.m(1); return 0; }
"""
    res = _ex("src/k.cpp", "cpp", cpp_code)
    names = {s.qualname: s for s in res.symbols}
    assert "K" in names and names["K"].kind == "class"
    assert names["K.m"].kind == "method"
    assert [(c.receiver, c.name) for c in names["K.m"].calls] == [(None, "helper"), ("this", "n")]
    assert names["K.m"].parent == names["K"].id
    assert [(c.receiver, c.name) for c in names["main"].calls] == [("k", "m")]


def test_csharp() -> None:
    code = """
using System;
using App.Services;
namespace App {
  [ApiController]
  public class C : ControllerBase {
    public C(ISvc s) { _s = s; }
    [HttpGet("x")] public async Task<int> Get(int n) { return await _s.Run(n) + Helper(n); }
    static int Helper(int n) => n;
    public static void Main(string[] args) { new C(null).Get(1); }
  }
}
"""
    res = _ex("App/C.cs", "csharp", code)
    names = {s.name: s for s in res.symbols}
    assert names["Get"].decorators == ['HttpGet("x")']
    assert names["Get"].returns == "Task<int>"
    assert [(c.receiver, c.name) for c in names["Get"].calls] == [("_s", "Run"), (None, "Helper")]
    assert [c.name for c in names["Main"].calls] == ["Get", "C"]
    assert [i.module for i in res.file.imports] == ["System", "App.Services"]


def test_ruby() -> None:
    code = """
require 'sinatra'
require_relative 'util'
module M
  class A < B
    def initialize(x); @x = x; end
    def m(a, b = 1) helper(a); @x.run; end
    def self.s; new(1); end
  end
end
get '/x' do
  M::A.s
end
"""
    res = _ex("app.rb", "ruby", code)
    names = {s.qualname: s for s in res.symbols}
    assert {"M", "M.A", "M.A.initialize", "M.A.m", "M.A.s"} == set(names)
    assert [(c.receiver, c.name) for c in names["M.A.m"].calls] == [(None, "helper"), ("@x", "run")]
    assert [i.module for i in res.file.imports] == ["sinatra", "util"]
    assert "get" in {c.name for c in res.file.top_level_calls}


def test_php() -> None:
    code = """<?php
namespace App\\Http;
use App\\Models\\User;
require_once 'util.php';
class C extends Base {
  public function m(int $a): string { return $this->n($a) . helper($a) . User::find(1); }
  private function n($a) { return $a; }
}
function helper($a) { return new Thing($a); }
$app->get('/x', function() { return 1; });
"""
    res = _ex("src/C.php", "php", code)
    names = {s.qualname: s for s in res.symbols}
    assert {"C", "C.m", "C.n", "helper"} == set(names)
    assert [(c.receiver, c.name) for c in names["C.m"].calls] == [
        ("$this", "n"),
        (None, "helper"),
        ("User", "find"),
    ]
    assert [c.name for c in names["helper"].calls] == ["Thing"]
    assert names["C.m"].returns == "string"
    assert [(i.module, i.names) for i in res.file.imports] == [
        ("App\\Models\\User", ["User"]),
        ("util.php", []),
    ]
    assert ("$app", "get") in {(c.receiver, c.name) for c in res.file.top_level_calls}


def test_rust() -> None:
    code = """
use std::collections::HashMap;
use crate::util::helper;
mod handlers;
pub struct S { n: i32 }
impl S {
    /// Multiplies.
    pub fn m(&self, a: i32) -> i32 { helper(a) + self.n }
}
fn main() { let s = S { n: 1 }; s.m(2); Foo::new(); }
"""
    res = _ex("src/main.rs", "rust", code)
    names = {s.qualname: s for s in res.symbols}
    assert {"S", "S.m", "main"} == set(names)
    assert names["S.m"].docstring == "Multiplies."
    assert names["S.m"].returns == "i32" and names["S.m"].is_exported
    assert [(c.receiver, c.name) for c in names["main"].calls] == [("s", "m"), ("Foo", "new")]
    assert [i.module for i in res.file.imports] == [
        "std::collections::HashMap",
        "crate::util::helper",
        "mod handlers",
    ]


def test_syntax_errors_do_not_crash() -> None:
    res = _ex("bad.py", "python", "def broken(:\n  pass\nclass Ok:\n  def m(self): pass\n")
    assert res.file.parse_error is not None
    assert any(s.name == "m" for s in res.symbols)
