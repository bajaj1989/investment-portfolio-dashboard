from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Member(Base):
    __tablename__ = "member"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    relation: Mapped[str | None] = mapped_column(String(50))
    pan_last4: Mapped[str | None] = mapped_column(String(4))
    tax_slab: Mapped[float] = mapped_column(Float, default=0.30)
    residency: Mapped[str] = mapped_column(String(10), default="resident", server_default="resident")  # resident | nri

    accounts: Mapped[list["Account"]] = relationship(back_populates="member", cascade="all, delete-orphan")


class Account(Base):
    __tablename__ = "account"
    __table_args__ = (UniqueConstraint("member_id", "type", "external_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    member_id: Mapped[int] = mapped_column(ForeignKey("member.id"))
    type: Mapped[str] = mapped_column(String(20))  # zerodha | mf_folio | cryptocom | manual
    label: Mapped[str] = mapped_column(String(200))
    external_id: Mapped[str] = mapped_column(String(100), default="")

    member: Mapped[Member] = relationship(back_populates="accounts")


class Instrument(Base):
    __tablename__ = "instrument"
    __table_args__ = (UniqueConstraint("asset_class", "key"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    asset_class: Mapped[str] = mapped_column(String(10))  # stock | mf | crypto
    key: Mapped[str] = mapped_column(String(100))  # ISIN for stock/mf, symbol for crypto
    name: Mapped[str] = mapped_column(String(300))
    symbol: Mapped[str | None] = mapped_column(String(50))
    isin: Mapped[str | None] = mapped_column(String(20))
    amfi_code: Mapped[str | None] = mapped_column(String(20))
    coingecko_id: Mapped[str | None] = mapped_column(String(100))
    category: Mapped[str] = mapped_column(String(20), default="equity")  # equity | debt | hybrid | gold | other | crypto | fx
    sector: Mapped[str | None] = mapped_column(String(100))
    # Currency of this instrument's prices and transaction amounts.
    currency: Mapped[str] = mapped_column(String(3), default="INR", server_default="INR")


class Txn(Base):
    __tablename__ = "txn"

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("account.id"))
    instrument_id: Mapped[int] = mapped_column(ForeignKey("instrument.id"))
    date: Mapped[date] = mapped_column(Date)
    # BUY | SELL | DIVIDEND | FEE | SPLIT | TRANSFER_OUT
    type: Mapped[str] = mapped_column(String(15))
    units: Mapped[float] = mapped_column(Float, default=0.0)  # for SPLIT: new units per old unit
    price: Mapped[float] = mapped_column(Float, default=0.0)
    amount: Mapped[float] = mapped_column(Float, default=0.0)  # gross value, always positive
    fees: Mapped[float] = mapped_column(Float, default=0.0)
    tds: Mapped[float] = mapped_column(Float, default=0.0)
    note: Mapped[str | None] = mapped_column(String(300))
    source: Mapped[str] = mapped_column(String(30), default="manual")
    ext_ref: Mapped[str | None] = mapped_column(String(100), unique=True)


class Price(Base):
    __tablename__ = "price"

    instrument_id: Mapped[int] = mapped_column(ForeignKey("instrument.id"), primary_key=True)
    date: Mapped[date] = mapped_column(Date, primary_key=True)
    price: Mapped[float] = mapped_column(Float)


class FixedDeposit(Base):
    __tablename__ = "fixed_deposit"

    id: Mapped[int] = mapped_column(primary_key=True)
    member_id: Mapped[int] = mapped_column(ForeignKey("member.id"))
    bank: Mapped[str] = mapped_column(String(100))
    fd_number: Mapped[str | None] = mapped_column(String(50))
    fd_type: Mapped[str] = mapped_column(String(10), default="regular", server_default="regular")  # regular | nro | nre
    principal: Mapped[float] = mapped_column(Float)
    rate: Mapped[float] = mapped_column(Float)  # annual %, e.g. 7.1
    start_date: Mapped[date] = mapped_column(Date)
    maturity_date: Mapped[date] = mapped_column(Date)
    compounding: Mapped[str] = mapped_column(String(15), default="quarterly")  # monthly|quarterly|half_yearly|yearly|simple
    payout: Mapped[str] = mapped_column(String(15), default="cumulative")  # cumulative|monthly|quarterly|half_yearly|yearly
    auto_renew: Mapped[bool] = mapped_column(Boolean, default=False)
    tds_deducted: Mapped[float] = mapped_column(Float, default=0.0)
    status: Mapped[str] = mapped_column(String(10), default="active")  # active | closed
    notes: Mapped[str | None] = mapped_column(Text)


class Snapshot(Base):
    __tablename__ = "snapshot"

    date: Mapped[date] = mapped_column(Date, primary_key=True)
    member_id: Mapped[int] = mapped_column(ForeignKey("member.id"), primary_key=True)
    asset_class: Mapped[str] = mapped_column(String(10), primary_key=True)
    invested: Mapped[float] = mapped_column(Float)
    value: Mapped[float] = mapped_column(Float)


class Goal(Base):
    __tablename__ = "goal"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    member_id: Mapped[int | None] = mapped_column(ForeignKey("member.id"))  # None = whole family
    target_amount: Mapped[float] = mapped_column(Float)
    target_date: Mapped[date] = mapped_column(Date)
    asset_classes: Mapped[str] = mapped_column(String(50), default="stock,mf,crypto,fd")
    expected_return: Mapped[float] = mapped_column(Float, default=10.0)  # annual %


class ImportLog(Base):
    __tablename__ = "import_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    file_hash: Mapped[str] = mapped_column(String(64))
    file_name: Mapped[str] = mapped_column(String(300))
    importer: Mapped[str] = mapped_column(String(30))
    member_id: Mapped[int | None] = mapped_column(ForeignKey("member.id"))
    imported_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    rows_added: Mapped[int] = mapped_column(Integer, default=0)
    rows_skipped: Mapped[int] = mapped_column(Integer, default=0)


class AlertLog(Base):
    __tablename__ = "alert_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(200), unique=True)
    sent_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


class Setting(Base):
    __tablename__ = "setting"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[str] = mapped_column(Text)
