# clean up
rm(list = ls())
gc()
cat("\014")

# Set wd to script directory (RStudio)
script_dir <- dirname(rstudioapi::getSourceEditorContext()$path)
setwd(script_dir)
setwd("../..")

library(readr)
library(dplyr)
library(ggplot2)
library(tibble)

BIN_MIN <- 15

file_map <- tibble(
  csv_file = c("avg_employee_1.csv","avg_employee_3.csv","avg_employee_5.csv",
               "avg_employee_7.csv","avg_employee_9.csv","avg_employee_11.csv"),
  n_evs    = c(30, 60, 120, 30, 60, 120),
  charger_type = c("FCC","FCC","FCC","SCC","SCC","SCC")
)

# --- read all as character to avoid type conflicts, then cast what we need ---
df_all <- bind_rows(lapply(seq_len(nrow(file_map)), function(i) {
  read_csv(
    file_map$csv_file[i],
    show_col_types = FALSE,
    col_types = cols(.default = col_character())
  ) %>%
    mutate(
      n_evs = file_map$n_evs[i],
      charger_type = file_map$charger_type[i]
    )
}))

# If your ID is run_id instead of seed, set this to "run_id"
ID_COL <- if ("seed" %in% names(df_all)) "seed" else "run_id"

df_pwr <- df_all %>%
  filter(agent == "energy_sandbox", field == "power_output_kW") %>%
  mutate(
    value_num = as.numeric(value),
    time_num  = as.numeric(time),
    id_num    = as.numeric(.data[[ID_COL]])
  ) %>%
  filter(is.finite(value_num), is.finite(time_num)) %>%
  group_by(id_num, time_num, charging_column__strategy, n_evs, charger_type) %>%
  summarise(value = max(value_num), .groups = "drop") %>%
  mutate(
    dt  = as.POSIXct(time_num, origin = "1970-01-01", tz = "Europe/Vienna"),
    bin = as.POSIXct(floor(as.numeric(dt) / (BIN_MIN * 60)) * (BIN_MIN * 60),
                     origin = "1970-01-01", tz = "Europe/Vienna"),
    # ---- key change: time-of-day label only ----
    bin_tod = format(bin, "%H:%M"),
    # keep ordering correct on the axis
    bin_tod = factor(bin_tod, levels = unique(bin_tod)),
    n_evs_f = factor(n_evs, levels = c(30, 60, 120)),
    charger_type = factor(charger_type, levels = c("FCC","SCC"))
  )

plot_one <- function(n_target) {
  
  df_sub <- df_pwr %>% filter(n_evs == n_target)
  
  p <- ggplot(
    df_sub,
    aes(
      x = bin_tod,
      y = value,
      fill = charger_type,
      linetype = charging_column__strategy,
      group = interaction(bin_tod, charger_type, charging_column__strategy)
    )
  ) +
    geom_boxplot(
      outlier.shape = 16,
      outlier.size = 0.7,
      position = position_dodge2(width = 0.85, preserve = "single"),
      linewidth = 0.45
    )
  
  if (n_target == 120) {
    
    df_max <- df_sub %>%
      group_by(charger_type, charging_column__strategy) %>%
      summarise(max_power = max(value, na.rm = TRUE), .groups = "drop")
    
    p <- p +
      geom_hline(
        data = df_max,
        aes(
          yintercept = max_power,
          color = charger_type,
          linetype = charging_column__strategy
        ),
        linewidth = 0.9
      ) +
      geom_text(
        data = df_max,
        aes(
          x = Inf,                      # place at right side
          y = max_power,
          label = paste(round(max_power, 1),"kW"),  # 1 decimal
        ),
        hjust = 1.1,   # slightly inside plot
        vjust = -0.3,
        size = 3.5,
        inherit.aes = FALSE
      )
  }
  
  p <- p +
    labs(
      x = paste0("Time of day (", BIN_MIN, "-min bins)"),
      y = "Power output (kW)",
      fill = "Charger type",
      color = "Charger type",
      linetype = "Strategy"
    ) +
    theme_bw() +
    theme(axis.text.x = element_text(angle = 45, hjust = 1))+
    theme(
      legend.position = "bottom",
      legend.justification = "center",
      legend.direction = "horizontal",
      legend.box = "horizontal",
      
      legend.text = element_text(size = 12),
      legend.key.size = unit(1.5, "lines"),
      
      axis.text = element_text(size = 12),
      axis.title = element_text(size = 12),
      
      strip.text = element_text(size = 12)
    )
  
  return(p)
}

p_30  <- plot_one(30)
p_60  <- plot_one(60)
p_120 <- plot_one(120)

p_30
p_60
p_120

ggsave("PWR_BOX_30EV.pdf",  p_30,  width = 10, height = 5)
ggsave("PWR_BOX_60EV.pdf",  p_60,  width = 10, height = 5)
ggsave("PWR_BOX_120EV.pdf", p_120, width = 10, height = 5)
