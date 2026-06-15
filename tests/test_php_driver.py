from claudebackend.core.drivers.php import PHPDriver

D = PHPDriver()

# Composer manifest with PSR-4 autoload. The file must contain JSON with a single
# backslash in the prefix ("Acme\"), so the Python source uses four backslashes.
_COMPOSER = '{"autoload":{"psr-4":{"Acme\\\\":"src/"}}}'


# --- source identification ---


def test_is_source_file():
    assert D.is_source_file("x.php")
    assert not D.is_source_file("x.py")


# --- dependency extraction ---


def test_extract_imports_use():
    out = D.extract_imports(b"<?php\nuse Acme\\Foo;\nuse Acme\\Bar as B;\n")
    assert "Acme\\Foo" in out
    assert "Acme\\Bar" in out


def test_extract_imports_group_use():
    out = D.extract_imports(b"<?php\nuse Acme\\{Foo, Bar};\n")
    assert "Acme\\Foo" in out and "Acme\\Bar" in out


def test_extract_imports_include_require_literals():
    out = D.extract_imports(b"<?php\nrequire 'lib.php';\ninclude_once('inc/x.php');\n")
    assert "lib.php" in out and "inc/x.php" in out


def test_extract_imports_extends_implements():
    out = D.extract_imports(b"<?php\nclass A extends Base implements I1, I2 {}\n")
    assert "Base" in out and "I1" in out and "I2" in out


def test_has_dynamic_import():
    assert D.has_dynamic_import(b"<?php eval($x);")
    assert D.has_dynamic_import(b"<?php $f = $$name;")
    assert D.has_dynamic_import(b"<?php require $path;")
    assert D.has_dynamic_import(b"<?php call_user_func($cb);")
    assert not D.has_dynamic_import(b"<?php require 'lib.php';")


# --- module/PSR-4 resolution ---


def test_module_name():
    assert D.module_name("src/Models/User.php") == "src\\Models\\User"


def test_build_modmap_psr4(tmp_path):
    (tmp_path / "composer.json").write_text(_COMPOSER, encoding="utf-8")
    modmap = D.build_modmap(["src/Foo.php", "src/Models/User.php"], tmp_path)
    assert modmap["Acme\\Foo"] == "src/Foo.php"
    assert modmap["Acme\\Models\\User"] == "src/Models/User.php"


def test_resolve_fqcn_longest_prefix(tmp_path):
    (tmp_path / "composer.json").write_text(_COMPOSER, encoding="utf-8")
    rels = ["src/Foo.php", "src/Bar.php"]
    modmap = D.build_modmap(rels, tmp_path)
    assert D.resolve("Acme\\Foo", "src/Bar.php", modmap, set(rels)) == "src/Foo.php"
    assert D.resolve("Vendor\\Lib", "src/Bar.php", modmap, set(rels)) is None


def test_resolve_relative_include():
    rels = {"src/lib.php", "src/Bar.php"}
    assert D.resolve("lib.php", "src/Bar.php", {}, rels) == "src/lib.php"
    # ../lib.php from src/ -> lib.php at root, which is not in the repo set.
    assert D.resolve("../lib.php", "src/Bar.php", {}, rels) is None


def test_package_manifest(tmp_path):
    (tmp_path / "composer.json").write_text(
        '{"require":{"php":">=8.1","monolog/monolog":"^3"},'
        '"autoload":{"psr-4":{"Acme\\\\":"src/"}}}',
        encoding="utf-8",
    )
    m = D.package_manifest(tmp_path)
    assert "monolog/monolog" in m["deps"]
    assert m["autoload"]["Acme\\"] == "src/"


def test_package_manifest_missing_file(tmp_path):
    m = D.package_manifest(tmp_path)
    assert m == {"deps": [], "autoload": {}}


# --- deterministic SAST ---


def test_scan_candidate_sqli_concat():
    code = '<?php\n$q = "SELECT * FROM u WHERE id=" . $_GET[\'id\'];\n'
    findings = D.scan_candidate(code)
    sqli = [f for f in findings if f.test_id == "PHP-SQLI"]
    assert sqli, findings
    assert sqli[0].severity == "HIGH" and sqli[0].confidence == "MEDIUM"
    assert sqli[0].line == 2


def test_scan_candidate_eval():
    assert any(f.test_id == "PHP-EVAL" for f in D.scan_candidate("<?php eval($x);"))


def test_scan_candidate_cmd_injection():
    out = D.scan_candidate('<?php system($_GET["c"]);')
    assert any(f.test_id == "PHP-CMD-INJECT" for f in out)


def test_scan_candidate_lfi():
    out = D.scan_candidate('<?php include $_GET["p"];')
    assert any(f.test_id == "PHP-LFI-RFI" for f in out)


def test_scan_candidate_unserialize():
    out = D.scan_candidate('<?php $o = unserialize($_POST["data"]);')
    assert any(f.test_id == "PHP-UNSERIALIZE" for f in out)


def test_scan_candidate_xss_flagged_without_escaping():
    out = D.scan_candidate('<?php echo $_GET["x"];')
    assert any(f.test_id == "PHP-XSS" for f in out)


def test_scan_candidate_xss_safe_with_htmlspecialchars():
    out = D.scan_candidate('<?php echo htmlspecialchars($_GET["x"]);')
    assert not any(f.test_id == "PHP-XSS" for f in out)


def test_scan_candidate_clean_code_no_findings():
    assert D.scan_candidate("<?php\nfunction add($a, $b) { return $a + $b; }\n") == []


# --- prompt hints / verification shape ---


def test_default_and_version_label():
    assert D.default_version() == "php8.1"
    assert D.version_label() == "Target PHP version"


def test_syntax_check_valid_or_php_absent(tmp_path):
    # ok=True both when php validates a good file and when php is not installed.
    f = tmp_path / "ok.php"
    f.write_text("<?php\n$x = 1;\n", encoding="utf-8")
    assert D.syntax_check(f).ok is True


def test_verify_steps_keys_and_order(tmp_path):
    (tmp_path / "a.php").write_text("<?php\n$x = 1;\n", encoding="utf-8")
    steps = D.verify_steps(tmp_path, None)
    keys = [s.key for s in steps]
    assert keys[0] == "php -l"
    assert keys[1] in ("phpstan", "psalm")
    assert "phpunit" in keys
    assert keys[-1] == "php-sast"


def test_verify_steps_sast_surfaces_finding(tmp_path):
    (tmp_path / "u.php").write_text(
        '<?php\n$q = "SELECT * FROM u WHERE id=" . $_GET["id"];\n', encoding="utf-8"
    )
    steps = D.verify_steps(tmp_path, None)
    sast = next(s for s in steps if s.key == "php-sast")
    assert sast.security_issues
    assert any("PHP-SQLI" in s for s in sast.security_issues)


def test_verify_steps_never_fails_when_toolchain_absent(tmp_path):
    # With no php/phpstan/phpunit installed, no step should produce a build error.
    (tmp_path / "a.php").write_text("<?php\n$x = 1;\n", encoding="utf-8")
    steps = D.verify_steps(tmp_path, None)
    php_l = next(s for s in steps if s.key == "php -l")
    # php -l is either ok (php present, valid file) or skipped (php absent); never errors here.
    assert not php_l.errors


# --- review-driven regression tests ---


def test_build_modmap_longest_dir_wins_over_root(tmp_path):
    # A root ("") PSR-4 prefix must NOT shadow a more specific directory mapping.
    (tmp_path / "composer.json").write_text(
        '{"autoload":{"psr-4":{"Root\\\\":"","Lib\\\\":"lib/"}}}', encoding="utf-8"
    )
    modmap = D.build_modmap(["lib/Thing.php", "Top.php"], tmp_path)
    assert modmap["Lib\\Thing"] == "lib/Thing.php"  # specific dir wins
    assert modmap["Root\\Top"] == "Top.php"  # root prefix still maps root files


def test_build_modmap_overlapping_prefixes_longest_wins(tmp_path):
    (tmp_path / "composer.json").write_text(
        '{"autoload":{"psr-4":{"App\\\\":"src/","AppApi\\\\":"src/Api/"}}}',
        encoding="utf-8",
    )
    modmap = D.build_modmap(["src/Api/Handler.php"], tmp_path)
    assert modmap["AppApi\\Handler"] == "src/Api/Handler.php"


def test_scan_candidate_cmd_inject_allows_escapeshellarg():
    # The recommended-safe pattern must not be flagged (else the gate hard-blocks it).
    assert not any(
        f.test_id == "PHP-CMD-INJECT"
        for f in D.scan_candidate('<?php exec(escapeshellarg($cmd));')
    )
    # but a raw variable still flags
    assert any(
        f.test_id == "PHP-CMD-INJECT" for f in D.scan_candidate('<?php exec($cmd);')
    )


def test_scan_candidate_unserialize_wrapped():
    out = D.scan_candidate('<?php $o = unserialize(base64_decode($_POST["d"]));')
    assert any(f.test_id == "PHP-UNSERIALIZE" for f in out)


def test_scan_candidate_sqli_tolerates_semicolon_in_literal():
    code = '<?php $pdo->query("SET x=1; SELECT * FROM u WHERE id=$_GET[y]");'
    assert any(f.test_id == "PHP-SQLI" for f in D.scan_candidate(code))


def test_extract_imports_group_use_function_const():
    out = D.extract_imports(b"<?php\nuse Acme\\{function f, const C, Klass};\n")
    assert "Acme\\Klass" in out
    # malformed "Acme\function f" / "Acme\const C" must not leak in
    assert not any(" " in n for n in out)
