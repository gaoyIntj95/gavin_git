from fastapi import APIRouter, Depends, HTTPException, status
from datetime import datetime
from pathlib import Path
from typing import Any
import logging
from sqlalchemy.orm import Session

from app.api.auth import get_current_user, require_admin
from app.core.config import settings
from app.core.database import get_db
from app.models.carbon_market import CarbonMarketRecord
from app.models.allowance_account import AllowanceAccount
from app.models.allowance_transaction import AllowanceTransaction
from app.models.compliance_snapshot import ComplianceSnapshot
from app.models.compliance_param_version import ComplianceParamVersion
from app.models.market_price_config import MarketPriceConfig
from app.models.compliance_audit_log import ComplianceAuditLog
from app.schemas.carbon_market import (
    ComplianceHistoryListResponse,
    ComplianceHistoryResponse,
    AllowanceAccountCreateRequest,
    AllowanceAccountListResponse,
    AllowanceAccountResponse,
    AllowanceTxnCreateRequest,
    AllowanceTxnListResponse,
    AllowanceTxnResponse,
    ComplianceParamVersionCreateRequest,
    ComplianceParamVersionListResponse,
    ComplianceParamVersionResponse,
    ComplianceReportResponse,
    ComplianceSimulateRequest,
    ComplianceSimulateResponse,
    ComplianceSummaryResponse,
    MarketPriceDebugResponse,
    MarketPriceResponse,
    OptimizeRequest,
    OptimizeResponse,
    QuotaGapRequest,
    QuotaGapResponse,
    SnapshotCreateRequest,
    SnapshotListResponse,
    SnapshotResponse,
    MarketPriceConfigCreateRequest,
    MarketPriceConfigListResponse,
    MarketPriceConfigResponse,
)
from app.services.carbon_market_price_service import fetch_latest_price
from app.services.calculation_service import calculate_project_totals
from app.services.compliance_audit_service import (
    create_compliance_snapshot,
    get_project_compliance_history,
    log_compliance_audit,
    validate_compliance_parameters,
)
from app.services.carbon_market_service import (
    build_compliance_summary,
    calculate_quota_gap,
    optimize_compliance_cost,
    simulate_compliance_plans,
)
from app.services.project_service import ensure_project_exists

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/carbon-market", tags=["carbon-market"])


def _build_compliance_report_path(project_id: int) -> Path:
    stamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    return Path(settings.report_dir) / f"compliance_report_{project_id}_{stamp}.md"


@router.post("/quota-gap/{project_id}", response_model=QuotaGapResponse)
def quota_gap(
    project_id: int,
    payload: QuotaGapRequest,
    db: Session = Depends(get_db),
    current_user: Any = Depends(get_current_user),
) -> QuotaGapResponse:
    errors = validate_compliance_parameters(payload.model_dump())
    if errors:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="; ".join(errors))

    ensure_project_exists(db, project_id)
    totals = calculate_project_totals(db, project_id)
    free_quota, gap = calculate_quota_gap(totals["total_emission"], payload.allocation_method)
    
    record = CarbonMarketRecord(
        project_id=project_id,
        total_emission=totals["total_emission"],
        free_quota=free_quota,
        quota_gap=gap,
        carbon_price=90.0,
        ccer_price=60.0,
        green_electricity_price=70.0,
        allocation_method=payload.allocation_method,
        ccer_max_ratio=0.30,
        green_power_max_ratio=0.20,
        optimal_cost=0.0,
        created_by=current_user.id,
    )
    db.add(record)
    db.commit()
    
    log_compliance_audit(
        db,
        project_id=project_id,
        snapshot_id=None,
        action_type="calculate_quota_gap",
        action_description=f"计算配额缺口，分配方法: {payload.allocation_method}",
        old_value=None,
        new_value={
            "allocation_method": payload.allocation_method,
            "free_quota": free_quota,
            "quota_gap": gap,
        },
        created_by=current_user.id,
    )

    return QuotaGapResponse(total_emission=totals["total_emission"], free_quota=free_quota, quota_gap=gap, record_id=record.id)


@router.post("/optimize/{project_id}", response_model=OptimizeResponse)
def optimize(
    project_id: int,
    payload: OptimizeRequest,
    db: Session = Depends(get_db),
    current_user: Any = Depends(get_current_user),
) -> OptimizeResponse:
    errors = validate_compliance_parameters(payload.model_dump())
    if errors:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="; ".join(errors))

    ensure_project_exists(db, project_id)
    record = (
        db.query(CarbonMarketRecord)
        .filter(CarbonMarketRecord.project_id == project_id)
        .order_by(CarbonMarketRecord.created_at.desc())
        .first()
    )

    if not record:
        totals = calculate_project_totals(db, project_id)
        free_quota, gap = calculate_quota_gap(totals["total_emission"], "benchmark")
        record = CarbonMarketRecord(
            project_id=project_id,
            total_emission=totals["total_emission"],
            free_quota=free_quota,
            quota_gap=gap,
            carbon_price=payload.carbon_price,
            ccer_price=payload.ccer_price,
            green_electricity_price=payload.green_electricity_price,
            allocation_method="benchmark",
            ccer_max_ratio=payload.ccer_max_ratio,
            green_power_max_ratio=payload.green_power_max_ratio,
            optimal_cost=0.0,
            created_by=current_user.id,
        )
        db.add(record)
        db.commit()

    plan, cost = optimize_compliance_cost(
        quota_gap=record.quota_gap,
        carbon_price=payload.carbon_price,
        ccer_price=payload.ccer_price,
        green_electricity_price=payload.green_electricity_price,
    )

    old_plan = {
        "carbon_price": record.carbon_price,
        "ccer_price": record.ccer_price,
        "green_electricity_price": record.green_electricity_price,
    }

    record.carbon_price = payload.carbon_price
    record.ccer_price = payload.ccer_price
    record.green_electricity_price = payload.green_electricity_price
    record.optimal_cost = cost
    record.updated_by = current_user.id
    db.commit()

    log_compliance_audit(
        db,
        project_id=project_id,
        snapshot_id=None,
        action_type="optimize_compliance",
        action_description="优化履约成本",
        old_value=old_plan,
        new_value={
            "carbon_price": payload.carbon_price,
            "ccer_price": payload.ccer_price,
            "green_electricity_price": payload.green_electricity_price,
            "optimal_cost": cost,
        },
        changed_fields=["carbon_price", "ccer_price", "green_electricity_price", "optimal_cost"],
        created_by=current_user.id,
    )

    full_quota_cost = record.quota_gap * record.carbon_price
    return OptimizeResponse(optimal_plan=plan, total_cost=cost, saving_compared_to_full_quota=round(full_quota_cost - cost, 2))


@router.get("/summary/{project_id}", response_model=ComplianceSummaryResponse)
def compliance_summary(
    project_id: int,
    allocation_method: str = "benchmark",
    db: Session = Depends(get_db),
    current_user: Any = Depends(get_current_user),
) -> ComplianceSummaryResponse:
    ensure_project_exists(db, project_id)
    totals = calculate_project_totals(db, project_id)
    summary = build_compliance_summary(
        total_emission=totals["total_emission"],
        allocation_method=allocation_method,
    )
    return ComplianceSummaryResponse(project_id=project_id, **summary)


@router.post("/simulate/{project_id}", response_model=ComplianceSimulateResponse)
def compliance_simulate(
    project_id: int,
    payload: ComplianceSimulateRequest,
    db: Session = Depends(get_db),
    current_user: Any = Depends(get_current_user),
) -> ComplianceSimulateResponse:
    errors = validate_compliance_parameters(payload.model_dump())
    if errors:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="; ".join(errors))

    ensure_project_exists(db, project_id)
    totals = calculate_project_totals(db, project_id)
    result = simulate_compliance_plans(
        total_emission=totals["total_emission"],
        allocation_method=payload.allocation_method,
        carbon_price=payload.carbon_price,
        ccer_price=payload.ccer_price,
        green_electricity_price=payload.green_electricity_price,
        ccer_max_ratio=payload.ccer_max_ratio,
        green_power_max_ratio=payload.green_power_max_ratio,
    )

    summary = result["summary"]
    best_plan = min(result["plans"], key=lambda x: x["total_cost"])

    record = CarbonMarketRecord(
        project_id=project_id,
        total_emission=summary["total_emission"],
        free_quota=summary["free_quota"],
        quota_gap=summary["quota_gap"],
        carbon_price=payload.carbon_price,
        ccer_price=payload.ccer_price,
        green_electricity_price=payload.green_electricity_price,
        allocation_method=payload.allocation_method,
        ccer_max_ratio=payload.ccer_max_ratio,
        green_power_max_ratio=payload.green_power_max_ratio,
        optimal_cost=float(best_plan["total_cost"]),
        created_by=current_user.id,
    )
    db.add(record)
    db.commit()

    snapshot_id = None
    if payload.save_snapshot:
        snapshot = create_compliance_snapshot(
            db,
            project_id=project_id,
            snapshot_name=payload.snapshot_name or f"履约方案_{datetime.now().strftime('%Y%m%d_%H%M')}",
            allocation_method=payload.allocation_method,
            carbon_price=payload.carbon_price,
            ccer_price=payload.ccer_price,
            green_electricity_price=payload.green_electricity_price,
            total_emission=totals["total_emission"],
            ccer_max_ratio=payload.ccer_max_ratio,
            green_power_max_ratio=payload.green_power_max_ratio,
            created_by=current_user.id,
        )
        snapshot_id = snapshot.id

        log_compliance_audit(
            db,
            project_id=project_id,
            snapshot_id=snapshot_id,
            action_type="create_snapshot",
            action_description=f"保存履约方案快照: {snapshot.snapshot_name}",
            old_value=None,
            new_value=result["summary"],
            created_by=current_user.id,
        )

    return ComplianceSimulateResponse(
        summary=ComplianceSummaryResponse(project_id=project_id, **summary),
        plans=result["plans"],
        recommended_plan=result["recommended_plan"],
        recommended_saving_ratio=result["recommended_saving_ratio"],
        snapshot_id=snapshot_id,
    )


@router.post("/report/{project_id}", response_model=ComplianceReportResponse)
def compliance_report(
    project_id: int,
    payload: ComplianceSimulateRequest,
    db: Session = Depends(get_db),
    current_user: Any = Depends(get_current_user),
) -> ComplianceReportResponse:
    ensure_project_exists(db, project_id)
    totals = calculate_project_totals(db, project_id)
    result = simulate_compliance_plans(
        total_emission=totals["total_emission"],
        allocation_method=payload.allocation_method,
        carbon_price=payload.carbon_price,
        ccer_price=payload.ccer_price,
        green_electricity_price=payload.green_electricity_price,
        ccer_max_ratio=payload.ccer_max_ratio,
        green_power_max_ratio=payload.green_power_max_ratio,
    )
    path = _build_compliance_report_path(project_id)
    lines = [
        f"# 碳市场履约建议报告（项目 {project_id}）",
        "",
        f"- 生成时间: {datetime.utcnow().isoformat()}Z",
        f"- 生成人: {current_user.username}",
        f"- 总排放: {result['summary']['total_emission']} tCO2e",
        f"- 免费配额: {result['summary']['free_quota']} t",
        f"- 履约缺口: {result['summary']['quota_gap']} t",
        "",
        "## 方案对比",
    ]
    for plan in result["plans"]:
        lines.extend([
            f"- {plan['name']}: 成本={plan['total_cost']}, 配额={plan['quota_buy']}, CCER={plan['ccer_buy']}, 绿电={plan['green_power_buy']}",
        ])
    lines.extend([
        "",
        "## 推荐方案",
        f"- {result['recommended_plan']}",
        f"- 预计节省比例: {result['recommended_saving_ratio']:.2%}",
    ])
    path.write_text("\n".join(lines), encoding="utf-8")

    log_compliance_audit(
        db,
        project_id=project_id,
        snapshot_id=None,
        action_type="generate_report",
        action_description="生成履约报告",
        old_value=None,
        new_value={"file_path": str(path)},
        created_by=current_user.id,
    )

    return ComplianceReportResponse(file_path=str(path))


@router.post("/snapshots/{project_id}", response_model=SnapshotResponse)
def create_snapshot(
    project_id: int,
    payload: SnapshotCreateRequest,
    db: Session = Depends(get_db),
    current_user: Any = Depends(get_current_user),
) -> SnapshotResponse:
    ensure_project_exists(db, project_id)
    totals = calculate_project_totals(db, project_id)
    
    snapshot = create_compliance_snapshot(
        db,
        project_id=project_id,
        snapshot_name=payload.snapshot_name,
        allocation_method=payload.allocation_method,
        carbon_price=payload.carbon_price,
        ccer_price=payload.ccer_price,
        green_electricity_price=payload.green_electricity_price,
        total_emission=totals["total_emission"],
        ccer_max_ratio=payload.ccer_max_ratio,
        green_power_max_ratio=payload.green_power_max_ratio,
        created_by=current_user.id,
    )

    log_compliance_audit(
        db,
        project_id=project_id,
        snapshot_id=snapshot.id,
        action_type="create_snapshot",
        action_description=f"创建履约快照: {snapshot.snapshot_name}",
        old_value=None,
        new_value={"snapshot_id": snapshot.id},
        created_by=current_user.id,
    )

    return SnapshotResponse(
        id=snapshot.id,
        snapshot_name=snapshot.snapshot_name,
        allocation_method=snapshot.allocation_method,
        carbon_price=snapshot.carbon_price,
        ccer_price=snapshot.ccer_price,
        green_electricity_price=snapshot.green_electricity_price,
        total_emission=snapshot.total_emission,
        free_quota=snapshot.free_quota,
        quota_gap=snapshot.quota_gap,
        recommended_plan=snapshot.recommended_plan,
        recommended_saving_ratio=snapshot.recommended_saving_ratio,
        is_final=snapshot.is_final,
        created_at=snapshot.created_at,
        created_by=snapshot.created_by,
    )


@router.get("/snapshots/{project_id}", response_model=SnapshotListResponse)
def list_snapshots(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: Any = Depends(get_current_user),
) -> SnapshotListResponse:
    ensure_project_exists(db, project_id)
    snapshots = (
        db.query(ComplianceSnapshot)
        .filter(ComplianceSnapshot.project_id == project_id)
        .order_by(ComplianceSnapshot.created_at.desc())
        .all()
    )

    items = []
    for snapshot in snapshots:
        items.append({
            "id": snapshot.id,
            "snapshot_name": snapshot.snapshot_name,
            "allocation_method": snapshot.allocation_method,
            "carbon_price": snapshot.carbon_price,
            "ccer_price": snapshot.ccer_price,
            "green_electricity_price": snapshot.green_electricity_price,
            "total_emission": snapshot.total_emission,
            "free_quota": snapshot.free_quota,
            "quota_gap": snapshot.quota_gap,
            "recommended_plan": snapshot.recommended_plan,
            "recommended_saving_ratio": snapshot.recommended_saving_ratio,
            "is_final": snapshot.is_final,
            "created_at": snapshot.created_at,
            "created_by": snapshot.created_by,
        })

    return SnapshotListResponse(snapshots=items)


@router.patch("/snapshots/{snapshot_id}/final", response_model=SnapshotResponse)
def mark_snapshot_final(
    snapshot_id: int,
    reason: str | None = None,
    db: Session = Depends(get_db),
    current_user: Any = Depends(get_current_user),
) -> SnapshotResponse:
    snapshot = db.query(ComplianceSnapshot).filter(ComplianceSnapshot.id == snapshot_id).first()
    if not snapshot:
        raise HTTPException(status_code=404, detail="快照不存在")
    
    old_is_final = snapshot.is_final
    old_reason = snapshot.final_reason
    
    snapshot.is_final = True
    snapshot.final_reason = reason
    db.commit()
    
    log_compliance_audit(
        db,
        project_id=snapshot.project_id,
        snapshot_id=snapshot.id,
        action_type="mark_snapshot_final",
        action_description="标记快照为最终版本",
        old_value={"is_final": old_is_final, "final_reason": old_reason},
        new_value={"is_final": True, "final_reason": reason},
        created_by=current_user.id,
    )

    db.refresh(snapshot)
    return {
        "id": snapshot.id,
        "snapshot_name": snapshot.snapshot_name,
        "allocation_method": snapshot.allocation_method,
        "carbon_price": snapshot.carbon_price,
        "ccer_price": snapshot.ccer_price,
        "green_electricity_price": snapshot.green_electricity_price,
        "total_emission": snapshot.total_emission,
        "free_quota": snapshot.free_quota,
        "quota_gap": snapshot.quota_gap,
        "recommended_plan": snapshot.recommended_plan,
        "recommended_saving_ratio": snapshot.recommended_saving_ratio,
        "is_final": snapshot.is_final,
        "created_at": snapshot.created_at,
        "created_by": snapshot.created_by,
    }


@router.post("/price-configs/{project_id}", response_model=MarketPriceConfigResponse)
def create_price_config(
    project_id: int,
    payload: MarketPriceConfigCreateRequest,
    db: Session = Depends(get_db),
    current_user: Any = Depends(get_current_user),
) -> MarketPriceConfigResponse:
    ensure_project_exists(db, project_id)
    
    config = MarketPriceConfig(
        project_id=project_id,
        price_type=payload.price_type,
        price=payload.price,
        currency=payload.currency,
        effective_date=payload.effective_date,
        expiry_date=payload.expiry_date,
        source=payload.source,
        notes=payload.notes,
        created_by=current_user.id,
    )
    db.add(config)
    db.commit()
    db.refresh(config)

    log_compliance_audit(
        db,
        project_id=project_id,
        snapshot_id=None,
        action_type="create_price_config",
        action_description=f"创建价格配置: {payload.price_type}",
        old_value=None,
        new_value={"price_type": payload.price_type, "price": payload.price},
        created_by=current_user.id,
    )

    return MarketPriceConfigResponse(
        id=config.id,
        price_type=config.price_type,
        price=config.price,
        currency=config.currency,
        effective_date=config.effective_date,
        expiry_date=config.expiry_date,
        is_active=config.is_active,
        source=config.source,
        notes=config.notes,
        created_at=config.created_at,
        created_by=config.created_by,
    )


@router.get("/price-configs/{project_id}", response_model=MarketPriceConfigListResponse)
def list_price_configs(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: Any = Depends(get_current_user),
) -> MarketPriceConfigListResponse:
    ensure_project_exists(db, project_id)
    configs = (
        db.query(MarketPriceConfig)
        .filter(MarketPriceConfig.project_id == project_id)
        .order_by(MarketPriceConfig.effective_date.desc())
        .all()
    )

    items = []
    for config in configs:
        items.append({
            "id": config.id,
            "price_type": config.price_type,
            "price": config.price,
            "currency": config.currency,
            "effective_date": config.effective_date,
            "expiry_date": config.expiry_date,
            "is_active": config.is_active,
            "source": config.source,
            "notes": config.notes,
            "created_at": config.created_at,
            "created_by": config.created_by,
        })

    return MarketPriceConfigListResponse(configs=items)


@router.get("/history/{project_id}", response_model=ComplianceHistoryListResponse)
def get_history(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: Any = Depends(get_current_user),
) -> ComplianceHistoryListResponse:
    ensure_project_exists(db, project_id)
    history = get_project_compliance_history(db, project_id)
    total = len(history)
    
    items = []
    for record in history:
        items.append({
            "id": record["id"],
            "allocation_method": record["allocation_method"],
            "carbon_price": record["carbon_price"],
            "ccer_price": record["ccer_price"],
            "green_electricity_price": record["green_electricity_price"],
            "total_emission": record["total_emission"],
            "quota_gap": record["quota_gap"],
            "optimal_cost": record["optimal_cost"],
            "is_final": record["is_final"],
            "created_at": record["created_at"],
            "created_by": record["created_by"],
            "created_by_username": record["created_by_username"],
        })

    return ComplianceHistoryListResponse(records=items, total=total)


@router.post("/allowance-accounts/{project_id}", response_model=AllowanceAccountResponse)
def create_allowance_account(
    project_id: int,
    payload: AllowanceAccountCreateRequest,
    db: Session = Depends(get_db),
    current_user: Any = Depends(get_current_user),
) -> AllowanceAccountResponse:
    ensure_project_exists(db, project_id)
    row = AllowanceAccount(
        project_id=project_id,
        account_name=payload.account_name,
        account_code=payload.account_code,
        balance_quota=payload.balance_quota,
        ccer_balance=payload.ccer_balance,
        notes=payload.notes,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    log_compliance_audit(
        db,
        project_id=project_id,
        snapshot_id=None,
        action_type="create_allowance_account",
        action_description=f"创建配额账户: {payload.account_name}",
        old_value=None,
        new_value={"account_id": row.id, "account_code": row.account_code},
        created_by=current_user.id,
    )
    return {
        "id": row.id,
        "project_id": row.project_id,
        "account_name": row.account_name,
        "account_code": row.account_code,
        "balance_quota": row.balance_quota,
        "ccer_balance": row.ccer_balance,
        "notes": row.notes,
        "created_at": row.created_at,
    }


@router.get("/allowance-accounts/{project_id}", response_model=AllowanceAccountListResponse)
def list_allowance_accounts(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: Any = Depends(get_current_user),
) -> AllowanceAccountListResponse:
    ensure_project_exists(db, project_id)
    rows = (
        db.query(AllowanceAccount)
        .filter(AllowanceAccount.project_id == project_id)
        .order_by(AllowanceAccount.created_at.desc())
        .all()
    )
    return AllowanceAccountListResponse(
        accounts=[
            {
                "id": r.id,
                "project_id": r.project_id,
                "account_name": r.account_name,
                "account_code": r.account_code,
                "balance_quota": r.balance_quota,
                "ccer_balance": r.ccer_balance,
                "notes": r.notes,
                "created_at": r.created_at,
            }
            for r in rows
        ],
        total=len(rows),
    )


@router.post("/allowance-transactions/{project_id}", response_model=AllowanceTxnResponse)
def create_allowance_transaction(
    project_id: int,
    payload: AllowanceTxnCreateRequest,
    db: Session = Depends(get_db),
    current_user: Any = Depends(get_current_user),
) -> AllowanceTxnResponse:
    ensure_project_exists(db, project_id)
    total_amount = round(payload.quantity * payload.unit_price, 6)
    row = AllowanceTransaction(
        project_id=project_id,
        account_id=payload.account_id,
        txn_type=payload.txn_type,
        instrument=payload.instrument,
        quantity=payload.quantity,
        unit_price=payload.unit_price,
        total_amount=total_amount,
        txn_date=payload.txn_date,
        reference_no=payload.reference_no,
        notes=payload.notes,
        created_by=current_user.id,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    log_compliance_audit(
        db,
        project_id=project_id,
        snapshot_id=None,
        action_type="create_allowance_txn",
        action_description=f"新增配额台账流水: {payload.txn_type}/{payload.instrument}",
        old_value=None,
        new_value={"txn_id": row.id, "total_amount": total_amount},
        created_by=current_user.id,
    )
    return {
        "id": row.id,
        "project_id": row.project_id,
        "account_id": row.account_id,
        "txn_type": row.txn_type,
        "instrument": row.instrument,
        "quantity": row.quantity,
        "unit_price": row.unit_price,
        "total_amount": row.total_amount,
        "txn_date": row.txn_date,
        "reference_no": row.reference_no,
        "notes": row.notes,
        "created_by": row.created_by,
        "created_at": row.created_at,
    }


@router.get("/allowance-transactions/{project_id}", response_model=AllowanceTxnListResponse)
def list_allowance_transactions(
    project_id: int,
    limit: int = 100,
    db: Session = Depends(get_db),
    current_user: Any = Depends(get_current_user),
) -> AllowanceTxnListResponse:
    ensure_project_exists(db, project_id)
    lim = max(1, min(int(limit), 1000))
    rows = (
        db.query(AllowanceTransaction)
        .filter(AllowanceTransaction.project_id == project_id)
        .order_by(AllowanceTransaction.txn_date.desc(), AllowanceTransaction.created_at.desc())
        .limit(lim)
        .all()
    )
    return AllowanceTxnListResponse(
        transactions=[
            {
                "id": r.id,
                "project_id": r.project_id,
                "account_id": r.account_id,
                "txn_type": r.txn_type,
                "instrument": r.instrument,
                "quantity": r.quantity,
                "unit_price": r.unit_price,
                "total_amount": r.total_amount,
                "txn_date": r.txn_date,
                "reference_no": r.reference_no,
                "notes": r.notes,
                "created_by": r.created_by,
                "created_at": r.created_at,
            }
            for r in rows
        ],
        total=len(rows),
    )


@router.post("/param-versions/{project_id}", response_model=ComplianceParamVersionResponse)
def create_param_version(
    project_id: int,
    payload: ComplianceParamVersionCreateRequest,
    db: Session = Depends(get_db),
    current_user: Any = Depends(get_current_user),
) -> ComplianceParamVersionResponse:
    ensure_project_exists(db, project_id)
    row = ComplianceParamVersion(
        project_id=project_id,
        version_name=payload.version_name,
        allocation_method=payload.allocation_method,
        carbon_price=payload.carbon_price,
        ccer_price=payload.ccer_price,
        green_electricity_price=payload.green_electricity_price,
        ccer_max_ratio=payload.ccer_max_ratio,
        green_power_max_ratio=payload.green_power_max_ratio,
        is_active=payload.is_active,
        notes=payload.notes,
        created_by=current_user.id,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.get("/param-versions/{project_id}", response_model=ComplianceParamVersionListResponse)
def list_param_versions(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: Any = Depends(get_current_user),
) -> ComplianceParamVersionListResponse:
    ensure_project_exists(db, project_id)
    rows = (
        db.query(ComplianceParamVersion)
        .filter(ComplianceParamVersion.project_id == project_id)
        .order_by(ComplianceParamVersion.created_at.desc())
        .all()
    )
    return ComplianceParamVersionListResponse(versions=rows, total=len(rows))


@router.get("/market-price", response_model=MarketPriceResponse)
def get_market_price(
    symbol: str = "CEA",
    force: bool = False,
) -> MarketPriceResponse:
    """Return the latest available carbon market price snapshot.

    Data is cached in memory for 10 minutes.  Pass ``force=true`` to
    bypass the cache and fetch a fresh price.

    The ``fallback_layer`` field indicates data freshness:
      0 = live scrape (tanpaifang.com)
      1 = AKShare regional pilot
      2 = hardcoded benchmark (offline)
    """
    logger.info("API /carbon-market/market-price symbol=%s force=%s", symbol, force)
    snap, _trace = fetch_latest_price(symbol=symbol, force=force)
    logger.info(
        "API /carbon-market/market-price → layer=%d price=%.2f source=%s",
        snap.fallback_layer, snap.price, snap.source,
    )
    return MarketPriceResponse(**snap.to_dict())


@router.get("/test-carbon-price", response_model=MarketPriceDebugResponse)
def test_carbon_price(
    symbol: str = "CEA",
    force: bool = True,
) -> MarketPriceDebugResponse:
    """Debug endpoint — returns full pipeline trace with execution details.

    Always forces a fresh fetch (ignores cache).  Use this to diagnose
    which tier is serving data and why higher tiers failed.
    """
    logger.info("API /carbon-market/test-carbon-price symbol=%s", symbol)
    snap, trace = fetch_latest_price(symbol=symbol, force=force)
    return MarketPriceDebugResponse(
        source=snap.source,
        success=snap.price > 0,
        price=snap.price,
        price_date=snap.price_date,
        volume=snap.volume,
        turnover=snap.turnover,
        fallback_layer=snap.fallback_layer,
        trace=trace,
        snapshot=MarketPriceResponse(**snap.to_dict()),
    )
