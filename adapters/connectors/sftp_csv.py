"""Example: an ERP that drops `customers_YYYYMMDD.csv` on SFTP every night.

Files are processed in name order; the checkpoint is the last file's date, so
each nightly file is read exactly once.
"""

from __future__ import annotations

import csv
import io
import re
from typing import Iterator

import paramiko

from ..base import Adapter, Record
from ..registry import register

FILE = re.compile(r"customers_(\d{8})\.csv$")


@register("sftp_csv")
class SftpCSV(Adapter):
    def _sftp(self) -> paramiko.SFTPClient:
        t = paramiko.Transport((self.config["host"], self.config.get("port", 22)))
        t.connect(username=self.config["username"], password=self.secret("password"))
        return paramiko.SFTPClient.from_transport(t)

    def pages(self, since: str | None) -> Iterator[list[dict]]:
        sftp = self._sftp()
        try:
            folder = self.config.get("folder", "/outbound")
            files = sorted(f for f in sftp.listdir(folder) if FILE.search(f))
            for name in files:
                day = FILE.search(name).group(1)
                stamp = f"{day[:4]}-{day[4:6]}-{day[6:]}T00:00:00Z"
                if since and stamp <= since:
                    continue
                with sftp.open(f"{folder}/{name}") as fh:
                    rows = list(csv.DictReader(io.StringIO(fh.read().decode("utf-8-sig"))))
                yield [{**row, "_file_stamp": stamp} for row in rows]
        finally:
            sftp.close()

    def to_record(self, item: dict) -> Record:
        cols = self.config["columns"]  # our field -> CSV header
        return Record(
            source=self.name,
            kind="customer",
            external_id=item[cols["id"]],
            updated_at=item["_file_stamp"],
            data={k: item.get(v) for k, v in cols.items() if k != "id"},
        )
