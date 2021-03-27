from fastapi import APIRouter, Depends
from pypika.functions import Date
from starlette.requests import Request
from tortoise.functions import Count, Function

from rearq import ReArq, constants
from rearq.server import templates
from rearq.server.depends import get_rearq
from rearq.server.models import JobResult

router = APIRouter()


class ToDate(Function):
    database_func = Date


@router.get("/")
async def index(request: Request, rearq: ReArq = Depends(get_rearq)):
    task_map = rearq.task_map
    task_num = len(task_map)
    workers_info = await rearq.redis.hgetall(constants.WORKER_KEY)
    worker_num = len(workers_info)
    run_times = await JobResult.all().count()
    result = (
        await JobResult.all()
        .annotate(count=Count("id"), date=ToDate("start_time"))
        .group_by("date", "success")
        .order_by("date")
        .values("date", "success", "count")
    )
    x_axis = []
    series = [
        {
            "name": "Success",
            "type": "line",
            "data": [],
            "lineStyle": {"color": "#198754"},
            "areaStyle": {"color": "#198754"},
            "stack": "total",
            "label": {"show": "true"},
        },
        {
            "name": "Fail",
            "type": "line",
            "lineStyle": {"color": "#dc3545"},
            "areaStyle": {"color": "#dc3545"},
            "stack": "total",
            "data": [],
            "label": {"show": "true"},
        },
    ]
    for item in result:
        date = str(item.get("date"))
        if date not in x_axis:
            x_axis.append(date)
        count = item.get("count")
        success = item.get("success")
        if success:
            series[0]["data"].append(count)
        else:
            series[1]["data"].append(count)
    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "page_title": "dashboard",
            "worker_num": worker_num,
            "task_num": task_num,
            "run_times": run_times,
            "x_axis": x_axis,
            "series": series,
        },
    )
