// Worldcup King of Bet - lanceur .exe
// Ouvre le dashboard dans le navigateur par defaut.
using System;
using System.Diagnostics;
using System.IO;
using System.Windows.Forms;

class Launcher
{
    [STAThread]
    static void Main()
    {
        string dir = AppDomain.CurrentDomain.BaseDirectory;
        string html = Path.Combine(dir, "WorldcupKingOfBet.html");
        if (!File.Exists(html))
        {
            MessageBox.Show("WorldcupKingOfBet.html introuvable.\nLe .exe doit rester dans le dossier 'app' du projet.",
                            "Worldcup King of Bet", MessageBoxButtons.OK, MessageBoxIcon.Error);
            return;
        }
        Process.Start(new ProcessStartInfo(html) { UseShellExecute = true });
    }
}
