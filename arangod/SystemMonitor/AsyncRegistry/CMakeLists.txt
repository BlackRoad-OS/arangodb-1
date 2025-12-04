add_library(arango_async_monitoring STATIC
  Feature.cpp
  Metrics.cpp
  RestHandler.cpp
)

target_link_libraries(arango_async_monitoring
  arango_crashhandler
  arango_forest
  arango_metrics_base
  immer
)
