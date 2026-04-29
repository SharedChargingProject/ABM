# clean up
rm(list = ls())
gc()
cat("\014")

# Set wd to script directory (RStudio)
script_dir <- dirname(rstudioapi::getSourceEditorContext()$path)
setwd(script_dir)
#setwd("..")

library(readr)
library(dplyr)
library(tidyr)
library(ggplot2)

file_name <- "fully_loaded_timeRes_LA.csv"

safe_mean <- function(x) {
  x <- x[is.finite(x) & !is.na(x)]
  if (length(x) == 0) return(NA_real_)
  mean(x)
}

safe_sd <- function(x) {
  x <- x[is.finite(x) & !is.na(x)]
  if (length(x) <= 1) return(0)
  sd(x)
}

df <- read_csv(
  file_name,
  col_types = cols(.default = col_character()),
  show_col_types = FALSE
)

if (!"SWRM__replan_interval_slots" %in% names(df)) {
  stop("Column SWRM__replan_interval_slots not found in CSV.")
}

strategy_col <- if ("charging_column__strategy" %in% names(df)) {
  df$charging_column__strategy
} else {
  rep("SWRM", nrow(df))
}

base_df <- df %>%
  mutate(strategy = strategy_col) %>%
  transmute(
    time_num = suppressWarnings(as.numeric(time)),
    seed = as.character(seed),
    strategy = strategy,
    lookahead_h = suppressWarnings(as.numeric(SWRM__look_ahead_time_h)),
    replan_interval_slots = suppressWarnings(as.numeric(SWRM__replan_interval_slots)),
    time_resolution = suppressWarnings(as.numeric(simulation__time_resolution)),
    agent = agent,
    field = field,
    value_num = suppressWarnings(as.numeric(value))
  ) %>%
  filter(strategy == "SWRM") %>%
  filter(!is.na(time_num)) %>%
  filter(!is.na(lookahead_h)) %>%
  filter(!is.na(replan_interval_slots)) %>%
  filter(!is.na(time_resolution))

# final total_cost and total_energy_received per EV
ev_final <- base_df %>%
  filter(grepl("^ev_", agent)) %>%
  filter(field %in% c("total_cost", "total_energy_received")) %>%
  filter(!is.na(value_num)) %>%
  arrange(seed, time_resolution, lookahead_h, replan_interval_slots, agent, field, time_num) %>%
  group_by(seed, time_resolution, lookahead_h, replan_interval_slots, agent, field) %>%
  summarise(
    final_value = dplyr::last(value_num),
    .groups = "drop"
  ) %>%
  pivot_wider(
    names_from = field,
    values_from = final_value
  ) %>%
  filter(
    !is.na(total_cost),
    !is.na(total_energy_received),
    total_energy_received > 0
  ) %>%
  mutate(
    cost_per_kwh = total_cost / total_energy_received
  )

# average users once per seed
per_seed <- ev_final %>%
  group_by(time_resolution, lookahead_h, replan_interval_slots, seed) %>%
  summarise(
    avg_user_cost = safe_mean(cost_per_kwh),
    .groups = "drop"
  )

# then average seeds for each time resolution, look-ahead, and replan interval
plot_df <- per_seed %>%
  group_by(time_resolution, lookahead_h, replan_interval_slots) %>%
  summarise(
    mean_user_cost = safe_mean(avg_user_cost),
    sd_user_cost = safe_sd(avg_user_cost),
    nseeds = n(),
    .groups = "drop"
  ) %>%
  arrange(time_resolution, lookahead_h, replan_interval_slots) %>%
  mutate(
    time_resolution_f = factor(time_resolution),
    lookahead_f = factor(lookahead_h)
  )

print(plot_df)

print(unique(plot_df$time_resolution))

res_in <- c(15, 30, 60, 120)

plot_df <- per_seed %>%
  group_by(time_resolution, lookahead_h, replan_interval_slots) %>%
  summarise(
    mean_user_cost = safe_mean(avg_user_cost),
    sd_user_cost = safe_sd(avg_user_cost),
    nseeds = n(),
    .groups = "drop"
  ) %>%
  arrange(time_resolution, lookahead_h, replan_interval_slots) %>%
  mutate(
    time_resolution_f = factor(time_resolution),
    lookahead_f = factor(lookahead_h),
    replan_interval_f = factor(replan_interval_slots)
  )

res_in <- c(15, 30, 60, 120)

plot_df <- plot_df %>%
  mutate(
    time_resolution_f = factor(time_resolution),
    lookahead_f = factor(lookahead_h),
    replan_interval_f = factor(replan_interval_slots),
    time_resolution_lab = paste0("Deltat == ", time_resolution, "~s")
  )

plot_df_filtered <- plot_df %>%
  filter(time_resolution %in% res_in) %>%
  filter(lookahead_h >= 2)

p <- ggplot(
  plot_df_filtered,
  aes(
    x = lookahead_h,
    y = mean_user_cost,
    color = replan_interval_f,
    fill = replan_interval_f,
    group = replan_interval_f
  )
) +
  geom_line(linewidth = 1.2) +
  geom_point(size = 2) +
  facet_wrap(
    ~ time_resolution_lab,
    scales = "free_x",
    labeller = label_parsed
  ) +
  scale_x_continuous(
    breaks = sort(unique(plot_df_filtered$lookahead_h))
  ) +
  labs(
    x = "Look-ahead time (h)",
    y = "Average user cost (€/kWh)",
    color = "Replan interval (slots)",
    fill = "Replan interval (slots)"
  ) +
  theme_minimal(base_size = 12) +
  theme(
    legend.position = "bottom",
    legend.direction = "horizontal"
  ) +
  guides(
    color = guide_legend(nrow = 1),
    fill = guide_legend(nrow = 1)
  )

print(p)

dir.create("fully_loaded_timeRes_LA", showWarnings = FALSE, recursive = TRUE)

ggsave(
  "fully_loaded_timeRes_LA/fully_loaded_timeRes_LA_replan_interval_slots.pdf",
  plot = p,
  width = 9,
  height = 5
)