"""Normalized account history checks. Trades alone cannot reconstruct daily Sharpe."""
from datetime import date
from .common import require,number


def validate_history(daily,initial_nav):
    previous=initial_nav
    last=None
    for row in daily:
        date.fromisoformat(row["date"])
        require(last is None or row["date"]>last,"History dates must increase without duplicates")
        for key in ("nav","net_return","gross_return","turnover","transaction_cost","financing","financing_return","trades","benchmark_return"):
            number(row[key],key)
        require(row["nav"]>0,"Account history must have positive equity")
        require(abs(row["net_return"]-(row["nav"]/previous-1))<1e-8,"NAV and returns disagree; normalize deposits/withdrawals before importing")
        require(abs(row["financing_return"]-row["financing"]/previous)<1e-8,"Financing amount and return disagree")
        require(abs(row["gross_return"]-row["net_return"]-(row["transaction_cost"]+row["financing"])/previous)<1e-8,"Gross/net return and cost attribution disagree")
        require(row["trades"]>=0 and float(row["trades"]).is_integer(),"Trade counts must be nonnegative integers")
        require(row["turnover"]>=0 and row["transaction_cost"]>=0,"Negative turnover or transaction cost")
        for field in ("weights","units"):
            require(isinstance(row[field],dict),f"{field} must be a dictionary")
            for symbol,value in row[field].items():
                number(value,field+"."+symbol)
        previous=row["nav"]
        last=row["date"]
    return daily
