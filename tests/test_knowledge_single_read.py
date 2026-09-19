from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'company-agent-plugin/scripts'))
from company_agent.knowledge import discover_documents


class KnowledgeSingleReadTests(unittest.TestCase):
    def test_frontmatter_and_body_come_from_the_same_read(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'term.md'
            path.write_text('---\nid: term.one\nkind: term\n---\n한글 내용',encoding='utf-8')
            original=Path.read_text
            reads=[]
            def read(file,*args,**kwargs):
                reads.append(file)
                return original(file,*args,**kwargs)
            with patch.object(Path,'read_text',read):
                docs,issues=discover_documents(Path(temp))
            self.assertEqual([path],reads)
            self.assertEqual([],issues)
            self.assertEqual('한글 내용\n',docs[0].body)


if __name__=='__main__':unittest.main()
