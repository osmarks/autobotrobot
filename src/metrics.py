import prometheus_client

achievements_achieved = prometheus_client.Counter("abr_achievements", "Achievements achieved by users")
reminders_fired = prometheus_client.Counter("abr_reminders", "Reminders successfully delivered to users")
role_transfers = prometheus_client.Counter("abr_role_transfers", "Times the esoserver transferable role has been transferred")