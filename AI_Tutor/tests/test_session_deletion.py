from types import SimpleNamespace
from unittest.mock import patch

import pytest

import memory.session_manager as sm_module
from memory.session_manager import SessionManager, SessionOwnershipError


SID = "11111111-aaaa-bbbb-cccc-000000000001"
OTHER_SID = "22222222-aaaa-bbbb-cccc-000000000002"


class _Query:

    def __init__(self, fake, table):
        self.fake, self.table, self.op, self.filters = fake, table, None, []

    def select(self, *_a, **_k):
        self.op = "select"; return self

    def delete(self):
        self.op = "delete"; return self

    def eq(self, col, val):
        self.filters.append(("eq", col, val)); return self

    def neq(self, col, val):
        self.filters.append(("neq", col, val)); return self

    def in_(self, col, vals):
        self.filters.append(("in", col, tuple(vals))); return self

    def execute(self):
        self.fake.log.append((self.table, self.op, tuple(self.filters)))
        if self.op == "select" and self.table == "pdfs":
            return SimpleNamespace(data=self.fake.pdf_rows(self.filters))
        return SimpleNamespace(data=[])


class _Bucket:

    def __init__(self, fake):
        self.fake = fake

    def list(self, folder, _opts=None):
        return [
            {"name": path.split("/", 1)[1]}
            for path in self.fake.files
            if path.startswith(folder + "/")
        ]

    def remove(self, paths):
        self.fake.log.append(("storage", "remove", tuple(paths)))
        if not self.fake.storage_fails:
            self.fake.files -= set(paths)


class FakeSupabase:

    def __init__(self, pdfs, files, storage_fails=False):
        self.pdfs = pdfs            # list of {"session_id", "pdf_path"}
        self.files = set(files)
        self.storage_fails = storage_fails
        self.log = []
        self.storage = SimpleNamespace(from_=lambda _b: _Bucket(self))

    def table(self, name):
        return _Query(self, name)

    def pdf_rows(self, filters):
        rows = self.pdfs
        for kind, col, val in filters:
            if kind == "eq":
                rows = [r for r in rows if r[col] == val]
            elif kind == "neq":
                rows = [r for r in rows if r[col] != val]
            elif kind == "in":
                rows = [r for r in rows if r[col] in val]
        return rows


def _delete(fake, owned=True):

    with patch.object(sm_module, "supabase", fake), \
         patch.object(SessionManager, "session_exists", return_value=owned):
        SessionManager(user_id="user-a").delete_session(SID)


def _deletes(fake):
    return [(t, f) for t, op, f in fake.log if op == "delete"]


class TestSessionDeletion:

    def test_all_session_resources_removed_in_safe_order(self):

        fake = FakeSupabase(
            pdfs=[{"session_id": SID, "pdf_path": f"{SID}/a.pdf"}],
            files={f"{SID}/a.pdf", f"{SID}/orphan.pdf", f"{OTHER_SID}/a.pdf"}
        )

        _delete(fake)

        tables = [t for t, _ in _deletes(fake)]
        assert tables == [
            "document_chunks", "selected_pdfs", "pdfs", "messages", "sessions"
        ]
        # Storage goes before any row is deleted.
        storage_idx = next(i for i, e in enumerate(fake.log) if e[0] == "storage")
        first_delete = next(i for i, e in enumerate(fake.log) if e[1] == "delete")
        assert storage_idx < first_delete
        # Recorded file and orphaned file both removed; other session kept.
        assert fake.files == {f"{OTHER_SID}/a.pdf"}
        # Every row delete is scoped to this session.
        for table, filters in _deletes(fake):
            key = "id" if table == "sessions" else "session_id"
            assert ("eq", key, SID) in filters
        assert ("eq", "user_id", "user-a") in _deletes(fake)[-1][1]

    def test_path_outside_session_folder_is_never_deleted(self):

        fake = FakeSupabase(
            pdfs=[{"session_id": SID, "pdf_path": f"{OTHER_SID}/shared.pdf"}],
            files={f"{OTHER_SID}/shared.pdf"}
        )

        _delete(fake)

        assert f"{OTHER_SID}/shared.pdf" in fake.files
        assert not any(e[0] == "storage" for e in fake.log)

    def test_file_referenced_by_another_session_is_kept(self):

        fake = FakeSupabase(
            pdfs=[
                {"session_id": SID, "pdf_path": f"{SID}/a.pdf"},
                {"session_id": OTHER_SID, "pdf_path": f"{SID}/a.pdf"},
            ],
            files={f"{SID}/a.pdf"}
        )

        _delete(fake)

        assert f"{SID}/a.pdf" in fake.files

    def test_storage_failure_stops_before_any_row_is_deleted(self):

        fake = FakeSupabase(
            pdfs=[{"session_id": SID, "pdf_path": f"{SID}/a.pdf"}],
            files={f"{SID}/a.pdf"},
            storage_fails=True
        )

        with pytest.raises(RuntimeError):
            _delete(fake)

        assert _deletes(fake) == []

    def test_not_owned_session_deletes_nothing(self):

        fake = FakeSupabase(pdfs=[], files={f"{SID}/a.pdf"})

        with pytest.raises(SessionOwnershipError):
            _delete(fake, owned=False)

        assert fake.log == []
        assert fake.files == {f"{SID}/a.pdf"}
