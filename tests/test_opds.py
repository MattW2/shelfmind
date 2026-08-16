import xml.etree.ElementTree as ET
import opds_client

def test_clean_xml_string():
    raw_xml = "Test & invalid \x00\x08 control chars"
    cleaned = opds_client.clean_xml_string(raw_xml)
    assert "\x00" not in cleaned
    assert "\x08" not in cleaned
    assert "&amp;" in cleaned

def test_parse_entry():
    entry_xml = """<entry xmlns="http://www.w3.org/2005/Atom" xmlns:dcterms="http://purl.org/dc/terms/" xmlns:xhtml="http://www.w3.org/1999/xhtml">
        <id>urn:uuid:abc-123</id>
        <title>Arthur Goes to Camp</title>
        <author><name>Marc Brown</name></author>
        <published>1982-01-01</published>
        <dcterms:language>en</dcterms:language>
        <category term="Children's Fiction"/>
        <link rel="http://opds-spec.org/image" href="/opds/cover/456"/>
        <link rel="http://opds-spec.org/acquisition" href="/opds/download/456/epub" type="application/epub+zip"/>
        <content type="xhtml">
            <xhtml:div>
                SERIES: Arthur Adventure Series [2.0]
                <xhtml:p>Arthur hates camp at first, but ends up having fun.</xhtml:p>
            </xhtml:div>
        </content>
    </entry>"""
    
    root = ET.fromstring(entry_xml)
    parsed = opds_client.parse_entry(root, "https://calibre.example.com")
    
    assert parsed["id"] == "urn:uuid:abc-123"
    assert parsed["title"] == "Arthur Goes to Camp"
    assert parsed["authors"] == "Marc Brown"
    assert parsed["series"] == "Arthur Adventure Series"
    assert parsed["series_index"] == 2.0
    assert parsed["categories"] == "Children's Fiction"
    assert parsed["cover_url"] == "https://calibre.example.com/opds/cover/456"
    assert parsed["download_url"] == "https://calibre.example.com/opds/download/456/epub"
    assert "Arthur hates camp" in parsed["description"]

def test_extract_calibre_integer_id():
    cover_url = "https://calibre.example.com/opds/cover/789"
    download_url = "https://calibre.example.com/opds/download/789/epub"
    
    assert opds_client.extract_calibre_integer_id(cover_url, download_url) == 789
    assert opds_client.extract_calibre_integer_id(None, download_url) == 789
    assert opds_client.extract_calibre_integer_id("https://example.com/none", None) is None
