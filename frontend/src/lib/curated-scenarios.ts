export type CuratedScenario = {
  id: string;
  title: string;
  region_label: string;
  monitor_id: string;
  headline: string;
  preview_event_id?: string;
  time_window?: {
    start_date: string;
    end_date: string;
  };
};

export const curatedScenarios: CuratedScenario[] = [];
