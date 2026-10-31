import sys

import pytest

from inspinia.solutions.pdf_latex import SolutionPdfCompileError
from inspinia.solutions.pdf_latex import compile_solution_tex_to_pdf


@pytest.mark.parametrize("restrict_file_access", [False, True])
@pytest.mark.parametrize("returncode", [0, 1])
def test_compiler_tolerates_non_utf8_diagnostics(tmp_path, restrict_file_access, returncode):
    driver = tmp_path / "latex-driver"
    driver.write_text(
        f"#!{sys.executable}\n"
        "import os\n"
        "from pathlib import Path\n"
        "os.write(1, b'Compiler output: \\xb6\\n')\n"
        "os.write(2, b'Compiler diagnostic: \\xb6\\n')\n"
        "Path('main.pdf').write_bytes(b'%PDF-1.4\\n')\n"
        f"raise SystemExit({returncode})\n",
        encoding="utf-8",
    )
    driver.chmod(0o700)
    params = {"timeout": 10, "latex_binary": str(driver), "restrict_file_access": restrict_file_access}

    if returncode:
        with pytest.raises(SolutionPdfCompileError, match="LaTeX compilation failed") as error:
            compile_solution_tex_to_pdf("example", **params)
        assert "Compiler diagnostic: \ufffd" in error.value.log_tail
    else:
        assert compile_solution_tex_to_pdf("example", **params) == b"%PDF-1.4\n"
