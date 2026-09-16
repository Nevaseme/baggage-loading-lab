import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
import zipfile


class PackageTests(unittest.TestCase):
    def setUp(self):
        spec=importlib.util.spec_from_file_location('package_under_test',Path(__file__).resolve().parents[1]/'tools/package_agent.py')
        self.module=importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.module)
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.source=self.root/'source'; self.source.mkdir()
        (self.source/'agent.py').write_bytes(b'class Agent:\n    pass\n')
        (self.source/'__init__.py').write_bytes(b'')

    def test_reproducible_archive_excludes_cache_and_preserves_source_bytes(self):
        cache=self.source/'__pycache__';cache.mkdir();(cache/'agent.pyc').write_bytes(b'noise')
        (self.source/'notes.log').write_text('not runtime input')
        first=self.module.build_package(self.source,'packing_agent',self.root/'one.zip')
        second=self.module.build_package(self.source,'packing_agent',self.root/'two.zip')
        self.assertEqual(first['sha256'],second['sha256'])
        with zipfile.ZipFile(self.root/'one.zip') as archive:
            self.assertIsNone(archive.testzip())
            self.assertEqual(set(archive.namelist()),{'packing_agent/agent.py','packing_agent/__init__.py','packing_agent/PACKAGE.json'})
            manifest=json.loads(archive.read('packing_agent/PACKAGE.json'))
            for name,digest in manifest['source_sha256'].items():
                payload=archive.read('packing_agent/'+name)
                self.assertEqual(payload,(self.source/name).read_bytes())
                self.assertEqual(hashlib.sha256(payload).hexdigest(),digest)

    def test_rejects_path_like_package_name_and_existing_output(self):
        with self.assertRaises(ValueError): self.module.build_package(self.source,'../escape',self.root/'bad.zip')
        output=self.root/'exists.zip';output.write_bytes(b'keep')
        with self.assertRaises(FileExistsError): self.module.build_package(self.source,'packing_agent',output)
        self.assertEqual(output.read_bytes(),b'keep')

    def test_syntax_failure_creates_no_archive(self):
        (self.source/'agent.py').write_text('invalid python !')
        output=self.root/'bad.zip'
        with self.assertRaises(SyntaxError): self.module.build_package(self.source,'packing_agent',output)
        self.assertFalse(output.exists())


if __name__=='__main__': unittest.main()
