class OpenTTDAI extends AIInfo
{
	function GetAuthor()      { return "Alistair"; }
	function GetName()        { return "OpenTTDAI"; }
	function GetDescription() { return "A rail-first OpenTTD AI: coal, oil, passenger and mail trains, plus shared ore/steel/goods, farm grain/livestock and wood/goods networks."; }
	function GetVersion()     { return 1; }
	function GetDate()        { return "2026-09-05"; }
	function CreateInstance() { return "OpenTTDAI"; }
	function GetShortName()   { return "OTAI"; }
	function GetAPIVersion()  { return "14"; }
	function MinVersionToLoad() { return 1; }

	function GetSettings()
	{
		AddSetting({
			name = "min_town_population",
			description = "Initial minimum town population (lowers when connections run out)",
			easy_value = 200,
			medium_value = 350,
			hard_value = 500,
			custom_value = 350,
			flags = 0,
			min_value = 50,
			max_value = 5000
		});
		AddSetting({
			name = "max_routes",
            description = "Maximum passenger routes (0 = unlimited)",
            easy_value = 0,
            medium_value = 0,
            hard_value = 0,
            custom_value = 0,
            flags = 0,
            min_value = 0,
            max_value = 200
		});
		AddSetting({
			name = "platform_length",
			description = "Station platform length (tiles)",
			easy_value = 5,
			medium_value = 4,
			hard_value = 3,
			custom_value = 4,
			flags = 0,
			min_value = 3,
			max_value = 7
		});
	}
}

RegisterAI(OpenTTDAI());
