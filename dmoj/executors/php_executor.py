from .base_executor import ScriptExecutor


class PHPExecutor(ScriptExecutor):
    ext = '.php'
    address_grace = 131072
    test_program = '<?php while($f = fgets(STDIN)) echo $f;'

    fs = ['.*/php[\w-]*\.ini$']

    def get_cmdline(self):
        return ['php', self._code]

    def get_fs(self):
        return self.fs + [self._code]
