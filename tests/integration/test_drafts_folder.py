import pytest
from imap_tools import MailBoxUnencrypted

pytestmark = pytest.mark.integration


def test_record_greenmail_folders(greenmail):
    g = greenmail
    with MailBoxUnencrypted(g["host"], port=g["port"]).login(g["user"], g["password"]) as mb:
        folders = [(f.name, tuple(f.flags or ())) for f in mb.folder.list()]
    print("GREENMAIL_FOLDERS", folders)
    assert folders  # the account has at least INBOX


def test_drafts_folder_resolvable_after_setup(drafts_ready):
    from mailbox_cleanup.folders import resolve_folder

    g = drafts_ready
    with MailBoxUnencrypted(g["host"], port=g["port"]).login(g["user"], g["password"]) as mb:
        assert resolve_folder(mb, "drafts") is not None
