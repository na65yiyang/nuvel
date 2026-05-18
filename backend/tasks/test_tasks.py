from tasks.celery_app import celery_app


@celery_app.task(name="tasks.add")
def add(a: float, b: float) -> float:
    return a + b
