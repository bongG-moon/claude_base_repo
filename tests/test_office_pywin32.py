from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch
from types import SimpleNamespace as NS

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'company-agent-plugin/scripts'))
from company_agent import office_pywin32 as reader


def collection(items):
    return NS(Count=len(items), Item=lambda i: items[i-1])


class OfficePythonTests(unittest.TestCase):
    def setup_reader(self, kind):
        request = {'file': r'C:\work\test.docx' if kind == 'word' else r'C:\work\test.pptx',
                   'kind': kind, 'start': 1, 'end': 5, 'maxChars': 10000}
        document = Mock(Permission=None)
        document.Paragraphs = collection([NS(Range=NS(Text='한글 본문\r'))])
        shape = NS(HasTable=0, HasTextFrame=-1, TextFrame=NS(TextRange=NS(Text='한글 슬라이드')))
        document.Slides = collection([NS(Shapes=collection([shape]))])
        documents = Mock(Count=0)
        documents.Open.return_value = document
        app = Mock(AutomationSecurity=1, Options=NS(UpdateLinksAtOpen=True))
        app.Documents = app.Presentations = documents
        client, com = Mock(), Mock()
        client.DispatchEx.return_value = app
        return request, document, documents, app, client, com

    def test_word_fixed_open_text_and_cleanup(self):
        request, doc, books, app, client, com = self.setup_reader('word')
        result = reader._read(request, client, com)
        self.assertTrue(result['ok'], result)
        self.assertEqual('한글 본문', result['items'][0]['text'])
        client.DispatchEx.assert_called_once_with('Word.Application')
        books.Open.assert_called_once_with(request['file'], False, True, False)
        doc.Close.assert_called_once_with(0)
        self.assertEqual(1, app.AutomationSecurity)
        self.assertTrue(app.Options.UpdateLinksAtOpen)
        app.Quit.assert_not_called()
        com.CoUninitialize.assert_called_once_with()
        self.assertEqual('unavailable', result['coverage']['officePermissionApi'])

    def test_powerpoint_fixed_open_and_table(self):
        request, doc, books, app, client, com = self.setup_reader('powerpoint')
        table = NS(Rows=NS(Count=1), Columns=NS(Count=1),
                   Cell=lambda r,c: NS(Shape=NS(TextFrame=NS(TextRange=NS(Text='실적 123')))))
        doc.Slides = collection([NS(Shapes=collection([NS(HasTable=-1, Table=table)]))])
        result = reader._read(request, client, com)
        self.assertTrue(result['ok'], result)
        self.assertEqual('실적 123', result['items'][0]['text'])
        client.DispatchEx.assert_called_once_with('PowerPoint.Application')
        books.Open.assert_called_once_with(request['file'], -1, 0, 0)
        doc.Close.assert_called_once_with()
        doc.Save.assert_not_called()
        app.Quit.assert_not_called()

    def test_already_open_source_not_closed(self):
        request, doc, books, app, client, com = self.setup_reader('word')
        books.Count = 1
        books.Item.return_value.FullName = request['file']
        result = reader._read(request, client, com)
        self.assertEqual('document_open', result['code'])
        books.Open.assert_not_called()
        doc.Close.assert_not_called()

    def test_restriction_never_extracts(self):
        request, doc, books, app, client, com = self.setup_reader('word')
        doc.Permission = NS(Enabled=True)
        with patch.object(reader, '_extract') as extract:
            result = reader._read(request, client, com)
        self.assertEqual('protected_input', result['code'])
        extract.assert_not_called()

    def test_denial_discards_partial_text_and_restores_options(self):
        request, doc, books, app, client, com = self.setup_reader('word')
        with patch.object(reader, '_extract', side_effect=PermissionError('secret text')):
            result = reader._read(request, client, com)
        self.assertEqual('permission_denied', result['code'])
        self.assertNotIn('items', result)
        self.assertNotIn('secret', str(result))
        doc.Close.assert_called_once_with(0)
        self.assertTrue(app.Options.UpdateLinksAtOpen)

    def test_partial_character_limit(self):
        request, doc, books, app, client, com = self.setup_reader('word')
        request['maxChars'] = 2
        result = reader._read(request, client, com)
        self.assertTrue(result['truncated'])
        self.assertEqual('한글', result['items'][0]['text'])

    def test_missing_dependency_does_not_launch_office(self):
        with patch('company_agent.office_reader.normalize', return_value={'kind':'word'}), \
                patch.object(reader.importlib, 'import_module', side_effect=ImportError), \
                patch.object(reader, '_read') as read:
            result = reader.read_document({'file': 'fixture'})
        self.assertEqual('office_dependencies_missing', result['code'])
        read.assert_not_called()

    def test_explicit_protection_blocks_before_import(self):
        with patch.object(reader.importlib, 'import_module') as imports:
            result = reader.read_document({'protection': 'blocked'})
        self.assertEqual('protected_input', result['code'])
        imports.assert_not_called()

    def test_empty_tables_still_have_a_global_read_limit(self):
        request, doc, books, app, client, com = self.setup_reader('powerpoint')
        cell = Mock(return_value=NS(Shape=NS(TextFrame=NS(TextRange=NS(Text='')))))
        table = NS(Rows=NS(Count=100), Columns=NS(Count=20), Cell=cell)
        doc.Slides = collection([NS(Shapes=collection([NS(HasTable=-1, Table=table)] * 2))])
        result = reader._read(request, client, com)
        self.assertTrue(result['ok'])
        self.assertTrue(result['truncated'])
        self.assertEqual(2000, cell.call_count)
        self.assertEqual([], result['items'])


if __name__ == '__main__': unittest.main()
