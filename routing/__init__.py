"""
Routing & Execution Orchestration — Agent 4.

Triggered by ratified allocation runs (Agent 3).  Builds a safe, reliable
route graph across humanitarian corridors, plans optimal convoys, and
monitors active missions for disruptions.

Module layout
─────────────
  seed_nodes   — static seed data (~40 Africa waypoints)
  scorer       — three-layer reliability/safety priors from ACLED + GDACS
  graph        — weighted directed graph with composite-score Dijkstra
  planner      — derive routing plans from a ratified AllocationRun
  monitor      — check overdue check-ins and new disruptions on active missions
"""
